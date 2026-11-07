"""Compatibility HTTP entry point."""
from .adapters.http import handler

def main():
    from .bootstrap import main as start
    start()

if __name__ == "__main__":
    main()
