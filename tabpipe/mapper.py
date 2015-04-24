"""
Implement the Mapper subunit.

"""
import luigi
import pandas as pd

from util import *
from core import TableTransform


class ColumnIdMapper(TableTransform):
    """Produce contiguous ids from a column; one for each unique value."""
    outname = luigi.Parameter(
        default=None,
        description='output filename; defualt: input-colname-idmap')

    def output(self):
        if self.outname:
            path = os.path.join(self.savedir, self.outname)
        else:
            outname = '-'.join([self.table.tname, self.colname, 'idmap'])
            path = os.path.join(self.savedir, outname)
        return luigi.LocalTarget(path)

    def run(self):
        """Produce contiguous id map; if nan values are present, they get their
        own unique id as well.
        """
        df = self.read_input_table()
        mapping = df[self.colname].drop_duplicates().reset_index()[self.colname]
        with self.output().open('w') as f:
            mapping.to_csv(f, index=True)


class ValueSubber(TableTransform):
    """Substitute existing column values for new ones using a 1:1 map."""
    idmap = luigi.Parameter(
        description='filename of idmap table')
    outname = luigi.Parameter(
        default=None,
        description='output filename; defualt: input-colname-idsub')

    def requires(self):
        return {
            'table': self.table,
            'idmap': self.idmap
        }

    def output(self):
        if self.outname:
            path = os.path.join(self.savedir, self.outname)
        else:
            outname = '-'.join([self.table.tname, self.colname, 'idsub'])
            path = os.path.join(self.savedir, outname)
        return luigi.LocalTarget(path)

    def run(self):
        """Replace all values in given colname using an idmap."""
        with self.input()['idmap'].open() as f:
            idmap = pd.read_csv(f, index_col=1, header=None)
            idmap = idmap[idmap.columns[0]]  # reduce to Series

        df = self.read_input_table()
        df[self.colname] = df[self.colname].apply(lambda val: idmap[val])

        with self.output().open('w') as f:
            df.to_csv(f, columns=self.cols, index=True)


class Mapper(TableTransform):
    """Replace 1+ set categorical columns with unique numerical id mappings."""
    outname = luigi.Parameter(
        default=None,
        description='output filename; default: input-Map<colnames-abbreviated>')

    def output(self):
        """Abbreviate colnames by attempting to take as few of the first few
        letters as necessary to get unique namings. Smash these all together and
        use title casing. So for instance: colnames=('grade', 'gpa', 'rank')
        would produce: MapGrGpRa.
        """
        if self.outname:
            path = os.path.join(self.savedir, self.outname)
        else:
            colname_abbrev = abbrev_names(self.cols)
            outname = '-'.join([self.table.tname, 'Map', colname-abbrev])
            path = os.path.join(self.savedir, outname)
        return luigi.LocalTarget(path)

    def __init__(self, *args, **kwargs):
        """Each column marked for mapping is mapped as follows:

        1.  An id mapping is generated by a ColumnIdMapper
        2.  A ValueSubber reads only the column of interest and its newly
            created idmap, substitues all values using the idmap, and writes
            that column to a new file.
        3.  A ColumnReplacer reads the new column with substited values and the
            original table and replaces the old column with the new one.

        The final task is the last ColumnReplacer in the chain.

        """
        super(Mapper, self).__init__(*args, **kwargs)

        self.mapper_tasks = []
        self.subber_tasks = []
        self.replacer_tasks = []
        for colname in self.cols:
            idmapper = ColumnIdMapper(table=self.table, colnames=colname)
            subber = ValueSubber(table=self.table, idmap=idmapper,
                                 colnames=colname)
            replacer = ColumnReplacer(
                table=self.table, replacement=subber, colnames=colname)

            self.mapper_tasks.append(mapper)
            self.subber_tasks.append(subber)
            self.replacer_tasks.append(replacer)

        self.final_task = replacer

    def run(self):
        schedule_task(self.final_task)

    @property
    def all_tasks(self):
        return self.mapper_tasks + self.subber_tasks + self.replacer_tasks

    def delete_intermediates(self):
        """Delete all intermediate output files."""
        for task in self.all_tasks:
            try:
                os.remove(task.output().path)
            except OSError:
                pass
