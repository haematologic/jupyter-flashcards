from pathlib import Path
from collections import OrderedDict
from time import time
from urllib.parse import urlparse
import re
import random
from threading import Timer
from IPython.display import IFrame

import pyexcel
import pyexcel_export

from .tags import to_raw_tags, tag_reader
from .utils import get_url_images_in_text
from .cache import cache_image_from_file, cache_image_from_url
from .card import CardQuiz, CardTuple
from .exceptions import (FileExtensionException, DatabaseHeaderException, NoDataError,
                         BadArgumentsException)


class Flashcards:
    SHEET_NAME = 'flashcards'

    def __init__(self, in_file):
        """

        :param str|Path in_file: can be a folder, *.xlsx or *.zip
        """
        self.modified = time()

        if not isinstance(in_file, Path):
            in_file = Path(in_file)

        self.working_dir = in_file.parent.joinpath(in_file.stem)

        self.image_dir = dict(
            _path=self.working_dir.joinpath(in_file.stem)
        )
        if in_file.exists():
            if in_file.suffix != '':
                if in_file.suffix == '.xlsx':
                    self.excel = in_file

                    for file in in_file.parent.joinpath(in_file.stem).iterdir():
                        self.image_dir[file.name] = file

                else:
                    raise FileExtensionException('Invalid file extension.')

                raw_data, self.meta = pyexcel_export.get_data(self.excel)

                self.data = self._load_raw_data(raw_data)
            else:
                self.excel = in_file.joinpath(in_file.stem + '.xlsx')
                self.working_dir = in_file.joinpath(in_file.stem)

                if not self.working_dir.exists():
                    self.working_dir.mkdir()

                raw_data, self.meta = pyexcel_export.get_data(self.excel)

                self.data = self._load_raw_data(raw_data)

                if in_file.joinpath(in_file.stem).exists():
                    for file in in_file.joinpath(in_file.stem).iterdir():
                        self.image_dir[file.name] = file

        else:
            if in_file.suffix == '.xlsx':
                self.excel = in_file
            else:
                raise FileExtensionException('Invalid file extension.')

            self.data = OrderedDict()
            self.meta = pyexcel_export.get_meta()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        pass

    def save(self, out_file=None):
        if out_file is None:
            out_file = self.working_dir

        if not isinstance(out_file, Path):
            out_file = Path(out_file)

        if out_file.is_dir():
            out_file = out_file.parent.joinpath(out_file.stem + '.xlsx')

        if out_file.suffix != '.xlsx':
            raise FileExtensionException('Unsupported file format.')

        if len(self.data) == 0:
            raise NoDataError("There is no data to save.")

        out_matrix = []
        header = list(self.data.values())[0]._fields
        out_matrix.append(header)

        for card_id, card_tuple in self.data.items():
            out_matrix.append(list(card_tuple))

        out_data = OrderedDict()
        out_data[self.SHEET_NAME] = out_matrix

        pyexcel_export.save_data(out_file=out_file, data=out_data, meta=self.meta)

    def add(self, **kwargs):
        if 'Front' not in kwargs.keys():
            raise BadArgumentsException("'Front' not in kwargs.keys()")

        item_id = int(time() * 1000)
        self.data[str(item_id)] = CardTuple(id=item_id)

        return self.update(item_id, **kwargs)

    def update(self, item_id: int, **kwargs):
        item_id = str(item_id)

        kwargs['Keywords'] = to_raw_tags(kwargs.get('Keywords', []))
        kwargs['Tags'] = to_raw_tags(kwargs.get('Tags', []))

        self._cache_image(item_id, kwargs.get('Front', ''))
        self._cache_image(item_id, kwargs.get('Back', ''))

        self.data[item_id]._update(kwargs)

        self.save()

        return self._preview_entries(self.data[item_id])

    def _cache_image(self, item_id, text):
        for url in get_url_images_in_text(text):
            image_name = '{}-{}'.format(item_id, Path(url).name)
            if not urlparse(url).netloc:
                cache_image_from_file(image_name=image_name, image_path=url, image_dir=self.image_dir)
            else:
                cache_image_from_url(image_name=image_name, image_url=url, image_dir=self.image_dir)

    def remove(self, item_id):
        self.data.pop(item_id)
        self.save()

    def find(self, keyword_regex: str = '', Tags= None):
        if Tags is None:
            tags = list()
        elif isinstance(Tags, str):
            tags = [Tags]
        else:
            tags = Tags

        matched_entries = set()
        for item_id, item in self.data.items():
            for keyword in (item.Front, item.Back, item.Keywords):
                if re.search(keyword_regex, keyword, flags=re.IGNORECASE):
                    matched_entries.add(item_id)

        for item_id in matched_entries:
            if len(tags) == 0:
                yield self.data[item_id]
            elif all([tag in tag_reader(self.data[item_id].Tags) for tag in tags]):
                yield self.data[item_id]

    def preview(self, keyword_regex: str='', tags: list=None,
                file_format='handsontable', width=800, height=300):

        file_output = self.working_dir.joinpath('preview.{}.html'.format(file_format))

        try:
            pyexcel.save_as(
                records=[item._asdict() for item in self.find(keyword_regex, tags)],
                dest_file_name=str(file_output.absolute()),
                dest_sheet_name='Preview'
            )

            return IFrame(str(file_output.relative_to('.')), width=width, height=height)
        finally:
            Timer(5, file_output.unlink).start()

    def _preview_entries(self, entries,
                         file_format='handsontable', width=800, height=150):
        """

        :param dict|OrderedDict|iter entries:
        :param file_format:
        :param width:
        :param height:
        :return:
        """
        if isinstance(entries, CardTuple):
            entries = [list(entries)]

        assert all([isinstance(entry, list) for entry in entries])
        assert all([isinstance(entry, list) for entry in entries])

        file_output = self.working_dir.joinpath('preview.{}.html'.format(file_format))

        try:
            pyexcel.save_as(
                array=list(entries),
                dest_file_name=str(file_output.absolute()),
                dest_mapdict=CardTuple._fields,
                dest_sheet_name='Preview'
            )

            return IFrame(str(file_output.relative_to('.')), width=width, height=height)
        finally:
            Timer(5, file_output.unlink).start()

    def quiz(self, keyword_regex: str='', Tags: list=None):
        all_records = list(self.find(keyword_regex, Tags))
        if len(all_records) == 0:
            return "There is no record matching the criteria."

        record = random.choice(all_records)

        return CardQuiz(record, image_dir=self.image_dir)

    def _load_raw_data(self, raw_data):
        if self.SHEET_NAME not in raw_data.keys():
            raise DatabaseHeaderException('Invalid Excel database.')

        data = OrderedDict()

        headers = raw_data[self.SHEET_NAME][0]
        if headers[0] != 'id':
            raise DatabaseHeaderException('Invalid Excel database.')

        for row in raw_data[self.SHEET_NAME][1:]:
            data[row[0]] = CardTuple(**dict(zip(headers, row)))

        return data