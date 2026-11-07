"""Compatibility HTTP entry point."""

from .adapters.http import handler as handler


def main():
    from .bootstrap import main as start

    start()


if __name__ == "__main__":
    main()
