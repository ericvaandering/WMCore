"""
MySQL implementation of File.Get
"""
from WMCore.WMBS.MySQL.Base import MySQLBase

class Get(MySQLBase):
    sql = """select id, lfn, size, events, run, lumi
                 from wmbs_file_details where lfn = :file"""
    #select id, lfn, size, events, run, lumi from wmbs_file_details where id = :file
    
    def getBinds(self, files=None):
        binds = []
        files = self.dbi.makelist(files)
        for f in files:
            binds.append({'file': f})
        return binds
    
    def format(self, result):
        out = result[0].fetchall()
        out = out[0]
        out = int(out[0]), str(out[1]), int(out[2]), int(out[3]), int(out[4]), int(out[5])
        return out 
        
    def execute(self, files=None, size=0, events=0, run=0, lumi=0, conn = None, transaction = False):
        binds = self.getBinds(files)
        
        self.logger.debug('File.Get binds: %s' % binds)
        result = self.dbi.processData(self.sql, binds, 
                         conn = conn, transaction = transaction)
        self.logger.debug('File.Get result: %s' % result)
        return self.format(result)