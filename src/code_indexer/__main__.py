import argparse
import sys
from pathlib import Path

from . import index_paths


def main() -> None:
    p = argparse.ArgumentParser(
        description='Extract structural skeletons from Python files.',
        epilog='PATH may be a file or directory. Defaults to the current directory.',
    )
    p.add_argument('paths', nargs='*', default=['.'], metavar='PATH',
                   help='files or directories to index (default: .)')
    p.add_argument('-o', '--output', metavar='FILE',
                   help='write output to FILE instead of stdout')
    p.add_argument('--exclude', action='append', default=[], metavar='PATTERN',
                   help='name or pattern to exclude (repeatable)')
    args = p.parse_args()

    result = index_paths(args.paths, exclude=args.exclude)

    if args.output:
        Path(args.output).write_text(result, encoding='utf-8')
        n = result.splitlines()[-1]  # last line is "# N files indexed"
        print(n, file=sys.stderr)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
