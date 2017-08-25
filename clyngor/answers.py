"""The Answers object"""


import re
from collections import defaultdict

from clyngor import as_pyasp, parsing


class Answers:
    """Proxy to the solver, generated by solving methods like solve.solve
    or inline.ASP.

    Iterable on the answer sets generated by the solver.
    Also expose some answer set formatting tunning.

    """

    def __init__(self, answers:iter):
        """Answer sets must be iterable of (predicate, args)"""
        self._answers = iter(answers)
        self._first_arg_only = False
        self._group_atoms = False
        self._as_pyasp = False
        self._sorted = False
        self._careful_parsing = False
        self._collapse_atoms= False
        self._collapse_args = True


    @property
    def first_arg_only(self):
        self._first_arg_only = True
        return self

    @property
    def by_predicate(self):
        self._group_atoms = True
        return self

    @property
    def as_pyasp(self):
        self._as_pyasp = True
        return self

    @property
    def sorted(self):
        self._sorted = True
        return self

    @property
    def careful_parsing(self):
        self._careful_parsing = True
        return self

    @property
    def atoms_as_string(self):
        self._collapse_atoms = True
        self._collapse_args = True
        return self

    @property
    def parse_args(self):
        self._careful_parsing = True  # needed to implement the collapse
        self._collapse_atoms = False
        self._collapse_args = False
        return self


    def __next__(self):
        return next(iter(self))


    def __iter__(self):
        """Yield answer sets"""
        for answer_set in self._answers:
            print('ASTPDET: ANSWERSET:', answer_set)
            answer_set = self._parse_answer(answer_set)
            answer_set = tuple(answer_set)
            print('ASTPBFT: ANSWERSET:', answer_set)
            yield self._format(answer_set)


    def _parse_answer(self, answer_set:str) -> iter:
        """Yield atoms as (pred, args) according to parsing options"""
        REG_ANSWER_SET = re.compile(r'([a-z][a-zA-Z0-9_]*)\(([^)]+)\)')
        if self._careful_parsing:
            print('CAREFUL PARSING:', answer_set)
            yield from parsing.parse_answer(answer_set,
                                            collapse_atoms=self._collapse_atoms,
                                            collapse_args=self._collapse_args)
        else:  # the good ol' split
            current_answer = set()
            for match in REG_ANSWER_SET.finditer(answer_set):
                pred, args = match.groups(0)
                if not self._collapse_atoms:  # else: atom as string
                    # parse also integers
                    args = tuple(
                        (int(arg) if (arg[1:] if arg.startswith('-') else arg).isnumeric() else arg)
                        for arg in args.split(',')
                    )
                yield pred, args


    def _format(self, answer_set) -> dict or frozenset:
        """Perform the formatting of the answer set according to
        formatting options.

        """
        sorted_tuple = lambda it: tuple(sorted(it))
        builder = sorted_tuple if self._sorted else frozenset
        if self._first_arg_only:
            answer_set = builder((pred, args[0] if args else ())
                                   for pred, args in answer_set)
        else:
            answer_set = builder((pred, tuple(args))
                                   for pred, args in answer_set)
        # NB: as_pyasp flag behave diffrently if group_atoms is activated
        if self._group_atoms:
            mapping = defaultdict(set)
            for pred, args in answer_set:
                if self._as_pyasp:
                    args = as_pyasp.Atom(pred, args)
                mapping[pred].add(args)
            return {pred: builder(args) for pred, args in mapping.items()}
        elif self._as_pyasp:
            return builder(as_pyasp.Atom(*atom) for atom in answer_set)
        return answer_set