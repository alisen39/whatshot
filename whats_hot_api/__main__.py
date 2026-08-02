import uvicorn

from whats_hot_api.app import create_app
from whats_hot_api.config import config


def main():
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=config.PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
