import os
import matplotlib.pyplot as plt
import numpy as np
import obspy.core
from obspy.core.utcdatetime import UTCDateTime

class Trace(obspy.core.Trace):
    """
    .. todo::
       document this class
    """
    def __init__(self, *args, **kwargs):
        if len(args) == 1:
            if isinstance(args[0], str) and os.path.isfile(args[0]):
                tr = obspy.core.read(args[0])[0]
                self.stats = tr.stats
                self.data = tr.data
            else:
                if isinstance(args[0], Dbptr):
                    dbptr = args[0]
                    if dbptr.query(dbTABLE_NAME) == 'wfdisc':
                        if dbptr.record >= 0 and dbptr.record < dbptr.record_count:
                            tr = obspy.core.read(dbptr.filename()[1])[0]
                            self.stats = tr.stats
                            self.data = tr.data
                        else:
                            raise ValueError("invalid record value: %d" % dbptr.record)
                    else:
                        raise ValueError("invalid table value: %d" % dbptr.table)
                else:
                    raise TypeError("invalid type: %s" % type(args[0]))
        else:
            mandatory_kwargs = ('station', 'channel', 'starttime', 'endtime')
            for kw in mandatory_kwargs:
                if kw not in kwargs:
                    raise ValueError("invalid keyword arguments")
            if not ("database_pointer" in kwargs or "database_path" in kwargs):
                    raise ValueError("invalid keyword arguments - specify database")
            starttime = validate_time(kwargs['starttime'])
            endtime = validate_time(kwargs['endtime'])
            if not isinstance(kwargs['station'], str):
                raise TypeError("invalid type: %s" % type(kwargs['station']))
            if not isinstance(kwargs['channel'], str):
                raise TypeError("inavlid type: %s" % type(kwargs['channel']))
            if 'database_path' in kwargs:
                if not isfile("%s.wfdisc" % kwargs['database_path']):
                    raise IOError("file not found: %s" % kwargs['database_path'])
                dbptr = dbopen(kwargs['database_path'], 'r')
            elif 'database_pointer' in kwargs and\
                    isinstance(kwargs['database_pointer'], Dbptr):
                dbptr = kwargs['database_pointer']
            else:
                raise ValueError("invalid keyword arguments")
            dbptr = dbptr.lookup(table='wfdisc')
            dbptr = dbptr.subset("sta =~ /%s/ && chan =~ /%s/ && "\
                    "endtime > _%f_ && time < _%f_" % (kwargs['station'],
                                                       kwargs['channel'],
                                                       kwargs['starttime'],
                                                       kwargs['endtime']))
            if dbptr.record_count == 0:
                raise IOError("no data found")
            st = Stream()
            for record in dbptr.iter_record():
                st += obspy.core.read(record.filename()[1],
                           starttime=starttime,
                           endtime=endtime)[0]
            st.merge()
            tr = st[0]
            self.stats = tr.stats
            self.data = tr.data

    def filter(self, *args, **kwargs):
        print self.stats.starttime
        self.trim(starttime=self.stats.starttime - 10, pad=True, fill_value=self.data.mean())
        print self.stats.starttime
        super(self.__class__, self).filter(*args, **kwargs)
        self.trim(starttime=self.stats.starttime + 10)
        print self.stats.starttime

    def noise_pad(self, twin, noise_twin=0):
        if noise_twin == 0:
            #Draw random noise.
            pass
            return
        noise = self.data[:noise_twin * self.stats.sampling_rate]
        npad_samples= twin * self.stats.sampling_rate
        self.trim(starttime=self.stats.starttime - twin, pad=True, fill_value=0.0)
        self.data[:npad_samples] = np.random.choice(noise, size=npad_samples, replace=True)

    def pick_fzhw(self,
                  q_thr=0.03,
                  dt_min=0.065,
                  max_vc=0.10,
                  vp=5.5,
                  snr=None,
                  kurt=None,
                  skew=None,
                  polar_flip=True):
        """
        Automatic picker for fault zone head waves. Only requires a single
        component (usually vertical) for usage. The picker makes an initial
        pick for the earliest onset of particle motion, and then makes two
        more in an attempt to find a direct P wave. If the initial pick and
        secondary detectors are too close in time, no fzhw is picked and only
        a direct P is identified.
        picks
        :type fault: float64 or [float64]*4
        :param fault: Station-fault distance or start-end coordinates of fault
        :type q_thr: float64
        :param q_thr: Maximum allowable time difference between P picks
        :type dt_min: float64
        :param dt_min: Minim allowed time separation
        :type max_vc: float64
        :param max_vc: maximum velocity contrast allowed
        :type vp: float64
        :param vp: P wave velocity (km/s) to assume for contrast calculation
        :type para: list of dictionaries
        :param para: Contains picker params for each picker
        :type detector: bool
        :param detector: Return CF traces on exit?
        :return: [picks, Final_P_pick, dt offset, CF traces (optional)]
        If a hw is not present, 'Final_P_pick' = None
        """
        SNR_par= {'on': 5,
                  'off': 4,
                  'sta': 0.1,
                  'lta': 10,
                  'peak_min': 0,
                  'dur_min': 0}

        if snr is not None:
            for key in snr:
                SNR_par[key] = snr[key] 

        K_par = {'on': 15,
                 'off': 2,
                 'wlen': 5,
                 'peak_min': 0}

        if kurt is not None:
            for key in kurt:
                K_par[key] = kurt[key]

        S_par = {'on': 3,
                 'off': 0.5,
                 'wlen': 5,
                 'peak_min': 0}

        if skew is not None:
            for key in skew:
                S_par[key] = skew[key]

        hw_pick, hw_alt, cft1 = self._first_pick(SNR_par)
        K_pick, K_alt, cft2 = self._K_pick(K_par)
        S_pick, S_alt, cft3 = self._S_pick(S_par)

        print hw_pick, K_pick, S_pick
        # Check that picks were made properly
        if hw_pick is None:
            return None
        head_wave = Detection(self.stats.station,
                              self.stats.channel,
                              self.stats.starttime + hw_pick,
                              'H')
        if K_pick is None or S_pick is None:
            return [head_wave]
        if np.mean([K_pick, S_pick]) < hw_pick:
            return [head_wave]
        cft = np.column_stack((cft1, cft2, cft3))

        dt = []
        dt.append(K_pick - hw_pick)
        dt.append(S_pick - hw_pick)

        fs = self.stats.sampling_rate
        hw_pick = int(hw_pick*fs)
        hw_alt = int(hw_alt*fs)
        K_pick = int(K_pick*fs)
        K_alt = int(K_alt*fs)
        S_pick = int(S_pick*fs)
        S_alt = int(S_alt*fs) 

        # Check for polarity reversal near skewness gradient peak
        half_width = S_alt - S_pick
        start = S_pick - half_width
        stop = S_pick + half_width
        skew_win = cft3[start:stop]
        zeros = np.where(np.diff(np.sign(skew_win)))[0] + 1

        if zeros.size == 0:
            return [head_wave]
        zeros += start
        p_flip = zeros[np.argmin(np.abs(zeros-S_pick))]
        P_pol = np.sign(cft3[p_flip])

        # Check for polarity reversal near hw pick (error checking)
        start = hw_pick - int(0.02*fs)
        stop = hw_pick + int(0.02*fs)
        hw_win = cft3[start:stop]
        zeros = np.where(np.diff(np.sign(hw_win)))[0] + 1
        if zeros.size == 0:
            HW_pol = np.sign(cft3[hw_pick])
            hw_flip = hw_pick
        elif zeros.size == 1:
            zeros += start
            hw_flip = zeros[np.argmin(np.abs(zeros-hw_pick))]
            HW_pol = np.sign(cft3[hw_flip])
        else:
            zeros += start
            hw_flip = zeros[-1]
            HW_pol = np.sign(cft3[hw_flip])
        if polar_flip:
            if HW_pol == P_pol:
                return [head_wave]

        # Make sure the skewness polarity doesn't flip multiple times
        hw_win = cft3[hw_flip+1:p_flip]
        zeros = np.where(np.diff(np.sign(hw_win)))[0] + 1
        if zeros.size > 0:
            return [head_wave]

        # Check that P picks are in specific range from HW pick
        vp_slow = vp - max_vc*vp
        dt_max = self.fzhw_p_dt(vp, vp_slow)
        if dt_max <= 0:
            return [head_wave]

        # Check that time differences are in allowed range
        if dt[0] < dt_min or dt[1] < dt_min:
            return [head_wave]
        if dt[0] > dt_max or dt[1] > dt_max:
            return [head_wave]
        # Check that picks are nearly coincident
        if np.abs(K_pick - S_pick) / fs  >= q_thr:
            return [head_wave]

        # Refine skewness pick with extrema near polarity flip
        minima = argrelmin(cft3[p_flip-1*half_width:p_flip+1])[0]
        if len(minima) >= 1:
            min_pick = minima[len(minima)-1] + p_flip - 1*half_width
        maxima = argrelmax(cft3[p_flip-1*half_width:p_flip+1])[0]
        if len(maxima) >= 1:
            max_pick = maxima[len(maxima)-1] + p_flip - 1*half_width
        if len(maxima) >= 1 and len(minima) >= 1:
            if max_pick > min_pick:
                S_pick = max_pick
            else:
                S_pick = min_pick
        elif len(maxima) >= 1:
            S_pick = max_pick
        elif len(minima) >= 1:
            S_pick = min_pick

        # Refining kurtosis pick with minima near polarity flip
        minima = argrelmin(cft2[p_flip-1*half_width:p_flip+1])[0]
        if len(minima) >= 1:
            K_pick = minima[len(minima)-1] + p_flip - 1*half_width
        hw_pick = hw_alt
        P_pick = (K_pick+S_pick)/2

        # Algorithm is concluded; mark first motion as FZHW
        return [Detection(self.stats.stations,
                          self.stats.channel,
                          self.stats.starttime + P_pick * self.stats.delta,
                          'P'),
                head_wave]

    def _first_pick(self, par):
        """
        'trace' is an ObsPy trace class containing a vertical cmp seismogram
        'par' is a dict containing the following quantities:
        'dur_min' is the minimum duration for trigger window
        'peak_min' is the minimum SNR value allowed for the peak STA/LTA
        'sta': short term average window length in seconds
        'lta': long term average window length in seconds
        'on': STA/LTA value for trigger window to turn on
        'off': STA/LTA value for trigger window to turn off
        """
        dur_min = par['dur_min']
        peak_min = par['peak_min']
        sta = par['sta']
        lta = par['lta']
        on = par['on']
        off = par['off']

        # Calculate characteristic function
        picks = []
        fs = self.stats.sampling_rate
        cft = self.copy()
        cft.trigger('recstalta', sta=sta, lta=lta)
        triggers = _trigger_onset(cft.data, on, off)
        for on_t, off_t in triggers:
            if off_t <= on_t:
                continue
            if (off_t - on_t)/fs < dur_min:
                continue
            MAX = np.max(cft.data[on_t:off_t])
            idx = np.argmax(cft.data[on_t:off_t])
            if MAX >= peak_min:
                picks.append((on_t, MAX))

        # Take the largest peak value
        if not picks:
            return None, None, None
        else:
            p_pick = max(picks, key=lambda x: x[1])[0]
            SNR = max(picks, key=lambda x: x[1])[1]

        start = p_pick - int(0.03*fs)
        alt_pick = np.argmin(cft.data[start:p_pick]) + start

        return p_pick/fs, alt_pick/fs, cft.data

    def _K_pick(self, par):
        """
        Make a pick for sharpest arrival using kurtosis
        'trace' is an ObsPy trace class containing a vertical cmp seismogram
        'par' is a dict with the following keys:
        'peak_min' is the minimum K value allowed for the peak
        'wlen': sliding window length in seconds
        'on': K value for trigger window to turn on
        'off': K value for trigger window to turn off
        """
        peak_min = par['peak_min']
        wlen = par['wlen']
        on = par['on']
        off = par['off']

        # Calculate characteristic function
        picks = []
        fs = self.stats.sampling_rate
        cft = self.copy()
        cft.data = pai_k(cft.data, int(wlen*fs))

        triggers = _trigger_onset(cft.data, on, off)
        for on_t, off_t in triggers:
            if off_t <= on_t:
                continue
            MAX = np.max(cft.data[on_t:off_t])
            idx = np.argmax(cft.data[on_t:off_t])
            if MAX >= peak_min:
                picks.append((on_t+idx, MAX))

        # Take the largest peak value
        if not picks:
            return None, None, None
        else:
            k_pick = max(picks, key=lambda x: x[1])[0]

        # Refining pick using nearby derivative
        alt_pick = k_pick
        start = k_pick - int(fs)
        grad = np.gradient(cft.data, 1/fs)
        if start <= 0:
            return None, None, None
        k_pick = np.argmax(grad[start:k_pick]) + start - 1
        return k_pick/fs, alt_pick/fs, cft.data

    def _S_pick(self, par):
        """
        Make a pick for sharpest arrival using skewness
        'trace' is an ObsPy trace class containing a vertical cmp seismogram
        'par' is a dict with the following keys:
        'peak_min' is the minimum S value allowed for the peak
        'wlen': sliding window length in seconds
        'on': S value for trigger window to turn on
        'off': S value for trigger window to turn off
        """
        peak_min = par['peak_min']
        wlen = par['wlen']
        on = par['on']
        off = par['off']

        # Calculate characteristic function
        picks = []
        fs = self.stats.sampling_rate
        cft_clean = self.copy()
        cft_clean.data = pai_s(cft_clean.data, int(wlen*fs))
        cft = cft_clean.copy()
        cft.data = np.abs(cft.data)

        triggers = _trigger_onset(cft.data, on, off)
        for on_t, off_t in triggers:
            if off_t <= on_t:
                continue
            MAX = np.max(cft.data[on_t:off_t])
            idx = np.argmax(cft.data[on_t:off_t])
            if MAX >= peak_min:
                picks.append((on_t+idx, MAX))

        # Take the largest peak value
        if not picks:
            return None, None, None
        else:
            s_pick = max(picks, key=lambda x: x[1])[0]

        # Refining pick using nearby derivative
        alt_pick = s_pick
        start = s_pick - int(fs)
        grad = np.gradient(cft.data, 1/fs)
        if start <= 0:
            return None, None, None
        s_pick = np.argmax(grad[start:s_pick]) + start - 1
        return s_pick/fs, alt_pick/fs, cft.data
        

    def plot(self,
             starttime=None,
             endtime=None,
             arrivals=None,
             detections=None,
             show=True,
             xticklabel_fmt=None):
        fig = plt.figure(figsize=(12, 3))
        ax = fig.add_subplot(1, 1, 1)
        ax = self.subplot(ax,
                          starttime=starttime,
                          endtime=endtime,
                          arrivals=arrivals,
                          detections=detections,
                          xticklabel_fmt=xticklabel_fmt)
        if show:
            plt.show()
        else:
            return fig

    def subplot(self,
                ax,
                starttime=None,
                endtime=None,
                arrivals=None,
                detections=None,
                xticklabel_fmt=None,
                set_xlabel=True):
        if xticklabel_fmt == None:
            xticklabel_fmt = "%Y%j %H:%M:%S.%f"
        starttime = float(starttime) if starttime else float(self.stats.starttime)
        first_sample = int(round((starttime - float(self.stats.starttime)) / self.stats.delta))
        endtime = float(endtime) if endtime else float(self.stats.endtime)
        npts = int((endtime - starttime) / self.stats.delta)
        time = [(starttime + i * self.stats.delta) for i in range(npts)]
        x_range = endtime - starttime
        y_range = max(self.data[first_sample:npts]) - min(self.data[first_sample:npts])
        aspect = (x_range / y_range) * 0.25
        ax.set_aspect(aspect)
        ax.plot(time, self.data[first_sample:npts], 'k')
        ax.set_xlim([float(self.stats.starttime), float(self.stats.endtime)])
        ax.set_xticklabels([UTCDateTime(time).strftime(xticklabel_fmt)\
                            for time in ax.get_xticks()],
                           rotation=10,
                           horizontalalignment='right')
        ax.set_ylabel(self.stats.channel, fontsize=16)
        if set_xlabel:
            stime = UTCDateTime(starttime).strftime("%Y%j")
            etime = UTCDateTime(endtime).strftime("%Y%j")
            if stime == etime:
                ax.set_xlabel(stime, fontsize=16)
            else:
                ax.set_xlabel("%s - %s" % (stime, etime),
                              fontsize=16)
        if arrivals: [ax.axvline(x=arrival.time,
                                 ymin=0.1,
                                 ymax=0.9,
                                 color='r',
                                 linewidth=2)\
                      for arrival in arrivals]
        if detections: [ax.axvline(x=detection.time,
                                   ymin=0.1,
                                   ymax=0.9,
                                   color='b',
                                   linewidth=2)\
                        for detection in detections]
        return ax

def _trigger_onset(cft, on, off):
    res = f90trigger(cft, on, off)
    ons = res[0]
    offs = res[1]
    idx = np.nonzero(ons)[0]
    ons = ons[idx]
    offs = offs[idx]
    return [list(a) for a in zip(ons, offs)] 

from seispy.core import Detection
from seispy.signal.statistics import f90trigger,\
                                     pai_k,\
                                     pai_s