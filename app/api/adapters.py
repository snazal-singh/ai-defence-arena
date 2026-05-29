import shutil
from typing import List

from fastapi import UploadFile


class FastAPIFileAdapter:
    """
    Adapts FastAPI's UploadFile to the werkzeug FileStorage interface that
    the existing service/controller layer expects (.filename, .content_type, .save()).
    """

    def __init__(self, upload_file: UploadFile):
        self._file = upload_file
        self.filename = upload_file.filename
        self.content_type = upload_file.content_type

    def save(self, path: str) -> None:
        self._file.file.seek(0)
        with open(path, "wb") as out:
            shutil.copyfileobj(self._file.file, out)
        self._file.file.seek(0)

    def read(self) -> bytes:
        self._file.file.seek(0)
        data = self._file.file.read()
        self._file.file.seek(0)
        return data

    def seek(self, pos: int) -> None:
        self._file.file.seek(pos)


class UploadFileList:
    """
    Adapts a FastAPI List[UploadFile] to the werkzeug ImmutableMultiDict interface
    that DocumentService and FileStorageService expect via .getlist("files").
    """

    def __init__(self, files: List[UploadFile]):
        self._files = [FastAPIFileAdapter(f) for f in files if f.filename]

    def getlist(self, key: str) -> List[FastAPIFileAdapter]:
        return self._files

    def __bool__(self) -> bool:
        return bool(self._files)

    def __len__(self) -> int:
        return len(self._files)
