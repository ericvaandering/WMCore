#!/usr/bin/env python
"""
_AddRunLumi_

MySQL implementation of AddRunLumi
"""

from past.builtins import basestring
from Utils.IteratorTools import grouper
from WMCore.Database.DBFormatter import DBFormatter


class AddRunLumi(DBFormatter):
    sql = """INSERT IGNORE wmbs_file_runlumi_map (fileid, run, lumi)
            select id, :run, :lumi from wmbs_file_details
            where lfn = :lfn"""

    def getBinds(self, filename=None, runs=None):

        binds = []

        if isinstance(filename, list):
            for entry in filename:
                binds.extend(self.getBinds(filename=entry['lfn'], runs=entry['runs']))
            return binds

        if isinstance(filename, basestring):
            lfn = filename
        elif isinstance(filename, dict):
            lfn = filename('lfn')
        else:
            raise Exception("Type of filename argument is not allowed: %s" \
                            % type(filename))

        if isinstance(runs, set):
            for run in runs:
                for lumi in run:
                    binds.append({'lfn': lfn,
                                  'run': run.run,
                                  'lumi': lumi})
        else:
            raise Exception("Type of runs argument is not allowed: %s" \
                            % type(runs))
        return binds

    def format(self, result):
        return True

    def execute(self, file=None, runs=None, conn=None, transaction=False):
        for sliceBinds in grouper(self.getBinds(file, runs), 10000):
            result = self.dbi.processData(self.sql, sliceBinds, conn=conn,
                                          transaction=transaction)
        return self.format(result)
