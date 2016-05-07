class Arrival:
    '''
    A container class for phase data.
    '''
    def __init__(self, *args, **kwargs):
        self.attributes = ()
        if len(args) == 1:
            import os
            import sys
            try:
                sys.path.append('%s/data/python' % os.environ['ANTELOPE'])
            except ImportError:
                #Presumably in the future an alternate parsing method
                #would be implemented for an object other than a Dbptr.
                raise ImportError("$ANTELOPE environment variable not set.")
            self._parse_Dbptr(args[0])
        else:
            self.sta = args[0]
            self.attributes += ('sta',)
            self.time = args[1]
            self.attributes += ('time',)
            self.iphase = args[2]
            self.attributes += ('iphase',)
            for attr in ('chan', 'deltim', 'qual', 'arid', 'tt_calc', 'predarr'):
                if attr in kwargs:
                    setattr(self, attr, kwargs[attr])
                else:
                    setattr(self, attr, None)
                self.attributes += (attr,)

    def _parse_Dbptr(self, dbptr):
        from antelope.datascope import Dbptr,\
                                       dbTABLE_FIELDS,\
                                       dbTABLE_NAME
        if not isinstance(dbptr, Dbptr):
            raise TypeError("__init__() received %s in argument position "\
                    "1 (requires antelope.datascope.Dbptr)")
        if dbptr.query(dbTABLE_NAME) != 'arrival':
            raise TypeError("invalid table index in antelope.datascope.Dbptr "\
                    "passed to __init__() at position 1 (pointer to '%s' "\
                    "table received, pointer to 'arrival' table required)")
        if dbptr.record < 0 or dbptr.record >= dbptr.record_count:
            raise IndexError("invalid record index in antelope.datascope.Dbptr "\
                    "passed to __init__() at argument position 1")
        for field in dbptr.query(dbTABLE_FIELDS):
            setattr(self, field, dbptr.getv(field)[0])
            self.attributes += (field,)

    def __str__(self):
        ret = "Arrival Object\n--------------\n"
        for attr in self.attributes:
            #ret += "%14s%s\n" % ((attr + ':'), getattr(self, attr))
            ret += "{:<14s}{}\n".format((attr + ':'), getattr(self, attr))
        return ret.rstrip()
