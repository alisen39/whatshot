"""History query errors with stable public codes."""


class HistoryError(Exception):
    code = "HISTORY_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class HistoryUnavailableError(HistoryError):
    code = "HISTORY_UNAVAILABLE"


class HistoryDisabledError(HistoryError):
    code = "HISTORY_DISABLED"


class HistoryQueryError(HistoryError):
    code = "HISTORY_QUERY_ERROR"


class HistoryCursorError(HistoryQueryError):
    code = "INVALID_HISTORY_CURSOR"


class HistoryRangeError(HistoryError):
    code = "QUERY_RANGE_TOO_LARGE"
