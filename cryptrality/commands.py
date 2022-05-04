#!/usr/bin/env python
# -*- coding: utf-8 -*-


from cryptrality.misc import (
    get_modules,
    DefaultHelpParser,
    SubcommandHelpFormatter,
)
from cryptrality import __version__
import cryptrality.subcommands


def main():
    """
    Execute the function with args
    """
    parser = DefaultHelpParser(
        prog="cryptrality",
        formatter_class=lambda prog: SubcommandHelpFormatter(
            prog, max_help_position=20, width=75
        ),
        description=("Cryptrality backtest tool"),
        add_help=True,
        epilog="This is version %s - %s - %s"
        % (__version__.VERSION, __version__.AUTHOR, __version__.DATE),
    )
    subparsers = parser.add_subparsers(dest="module")

    modules = get_modules(cryptrality.subcommands, subparsers, {})
    try:
        args, extra = parser.parse_known_args()
        if args.module in modules:
            modules[args.module](subparsers, args.module, extra)
            return None
        if args.module is None:
            return parser.print_help()
        return parser.parse_args(args)
    except IndexError as e:
        print(e)
        return parser.print_help()


if __name__ == "__main__":
    main()
