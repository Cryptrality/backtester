import os
import logging


class ExtendedLogger:
    def __init__(self, name: str, path: str, level: int) -> None:
        self.__name__ = name
        self.__path__ = os.path.join(path)
        if not os.path.exists(self.__path__):
            os.makedirs(self.__path__)
        self.log = logging.getLogger(self.__name__)
        self.log_file = os.path.join(self.__path__, "%s.log" % self.__name__)
        formatter = logging.Formatter(
            "%(levelname)s : %(asctime)s : %(message)s",
        )
        fileHandler = logging.FileHandler(self.log_file, mode="w")
        fileHandler.setFormatter(formatter)
        streamHandler = logging.StreamHandler()
        streamHandler.setFormatter(formatter)
        self.log.setLevel(level)
        self.log.addHandler(fileHandler)
        self.log.addHandler(streamHandler)


class SimpleLogger(ExtendedLogger):
    def __init__(
        self, name: str, path: str, level: int = logging.INFO
    ) -> None:
        super().__init__(name, path, level=level)
        self.log.info(
            "Writing %(name)s logs to folder %(path)s",
            {"path": self.__path__, "name": name},
        )
        self.sublogs = {}

    def add_log(self, name: str, level: int = logging.INFO) -> logging.Logger:
        self.sublogs[name] = SimpleLogger(name, self.__path__, level=level)
        return self.sublogs[name]
