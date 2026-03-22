from pygments import highlight
from pygments.formatters import TerminalTrueColorFormatter
from pygments.lexer import RegexLexer
from pygments.token import Comment, Generic, Keyword, Name, Number, Text


class SkeletonLexer(RegexLexer):
    name = 'Skeleton'

    tokens = {
        'root': [
            (r'# \d+ files? indexed',                               Comment.Single),
            (r'# \S+',                                              Generic.Heading),
            (r'(?:module doc|exports|imports|consts|classes|fns|tests)(?=:)', Keyword),
            (r'\[\d+(?:-\d+)?\]',                                  Number),
            (r'@[\w.]+',                                            Name.Decorator),
            (r'\n',                                                  Text),
            (r'.',                                                   Text),
        ]
    }


def colorize(text: str) -> str:
    return highlight(text, SkeletonLexer(), TerminalTrueColorFormatter(style='monokai'))
