"""Low level interface to clingo.

"""


import re
import json
import shlex
import tempfile
import subprocess
import clyngor
from clyngor.answers import Answers, ClingoAnswers
from clyngor.utils import cleaned_path, ASPSyntaxError, ASPWarning
from clyngor.parsing import parse_clasp_output, validate_clasp_stderr


def _default_running_sequence(programs:iter, files, solver_conf, options,
                              propagators:iter, observers:iter) -> 'Control':
    ctl = clyngor.clingo_module.Control(options)
    for propagator in propagators:
        solver.register_propagator(propagator)
    for observer in observers:
        solver.register_observer(observer)

    for fname in files:
        ctl.load(fname)
    ctl.ground(programs)

    # ctl.configuration = solver_conf  # TODO

    return ctl


def solve(files:iter=(), options:iter=[], inline:str=None,
          subproc_shell:bool=False, print_command:bool=False,
          nb_model:int=0, time_limit:int=0, constants:dict={},
          clean_path:bool=True, stats:bool=True,
          clingo_bin_path:str=None, error_on_warning:bool=False,
          use_clingo_module:bool=True, grounding_observers:iter=(),
          propagators:iter=(), solver_conf:object=None,
          running_sequence:callable=_default_running_sequence,
          programs:iter=(['base', ()],)) -> iter:
    """Run the solver on given files, with given options, and return
    an Answers instance yielding answer sets.

    files -- iterable of files feeding the solver
    options -- string or iterable of options for clingo
    inline -- ASP source code to feed the solver with
    subproc_shell -- use shell=True in subprocess call (NB: you should not)
    print_command -- print full command to stdout before running it
    clean_path -- clean the path of given files before using them
    stats -- will ask clingo for all stats, instead of just the minimal ones
    clingo_bin_path -- the path to the clingo binary
    error_on_warning -- raise an ASPWarning when encountering a clingo warning
    use_clingo_module -- will use the clingo module (if available)

    The following options needs the propagator support and/or python clingo module:
    grounding_observers -- iterable of observers to add to the grounding process
    propagators -- iterable of propagators to add to the solving process
    solver_conf -- clingo.Configuration instance, given to the running_sequence
    running_sequence -- If given, must be a callable taking programs, files and Configuration,
                        returning both clingo.Control and clingo.SolveHandle instances
    programs -- programs to feed the running sequence with.

    Shortcut to clingo's options:
    nb_model -- number of model to output (0 for all (default))
    time_limit -- zero or number of seconds to wait before interrupting solving
    constants -- mapping name -> value of constants for the grounding

    """
    files = [files] if isinstance(files, str) else files
    files = tuple(map(cleaned_path, files) if clean_path else files)
    if inline:
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as fd:
            fd.write(inline)
            files = tuple(files) + (fd.name,)
    run_command = command(files, options, nb_model, time_limit,
                          constants, stats, clingo_bin_path=clingo_bin_path)

    if print_command:
        print(run_command)

    if not files:
        # in this case, clingo will wait for stdin input, which will never come
        # so better not call clingo at all
        return Answers((), command=' '.join(run_command))

    if use_clingo_module and clyngor.have_clingo_module():
        options = options.split() if isinstance(options, str) else options
        solver = running_sequence(programs, files, solver_conf, options,
                                  propagators, grounding_observers)
        solver.configuration.solve.models = nb_model
        if time_limit != 0 or constants:
            raise ValueError("Options 'time_limit' and 'constants' are not "
                             "handled when used with python clingo module.")
        return ClingoAnswers(solver)
    else:
        clingo = subprocess.Popen(
            run_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=bool(subproc_shell),
        )
        stdout = (line.decode() for line in clingo.stdout)
        stderr = (line.decode() for line in clingo.stderr)
        statistics = {}

        return Answers(_gen_answers(stdout, stderr, statistics, error_on_warning),
                       command=' '.join(run_command),
                       statistics=statistics, with_optimization=True)


def command(files:iter=(), options:iter=[],
            nb_model:int=0, time_limit:int=0, constants:dict={},
            stats:bool=True, clingo_bin_path:str=None) -> iter:
    """Return the shell command running the solver on given files,
    with given options.

    files -- iterable of files feeding the solver
    options -- string or iterable of options for clingo
    clingo_bin_path -- the path to the clingo binary

    Shortcut to clingo's options:
    nb_model -- number of model to output (0 for all (default))
    time_limit -- zero or number of seconds to wait before interrupting solving
    constants -- mapping name -> value of constants for the grounding
    stats -- True to provides the --stats flag

    """
    files = [files] if isinstance(files, str) else list(files)
    options = list(shlex.split(options) if isinstance(options, str) else options)
    if constants:
        for name, value in constants.items():
            options.append('-c {}={}'.format(name,value))
    if time_limit:
        try:
            time_limit = int(time_limit)
        except ValueError:
            raise ValueError("Time limit should be integer, not " + type(time_limit).__name__)
        options.append('--time-limit=' + str(time_limit))
    if nb_model:
        try:
            nb_model = int(nb_model)
        except ValueError:
            raise ValueError("Number of model must be int, not " + type(nb_model).__name__)
        if nb_model < 0:
            raise ValueError("Number of model must be >= 0.")
    else:
        nb_model = 0
    if stats:
        options.append('--stats')

    return [clingo_bin_path or clyngor.CLINGO_BIN_PATH,
            *options, *files, '-n ' + str(nb_model)]


def clingo_version(clingo_bin_path:str=None) -> dict:
    """Return clingo's version information in a dict"""
    clingo = subprocess.Popen(
        [clingo_bin_path or clyngor.CLINGO_BIN_PATH, '--version', '--outf=2'],
        stderr = subprocess.PIPE,
        stdout = subprocess.PIPE,
    )
    fields = {
        'address model': re.compile(r'Address model: ([3264]{2})-bit'),
        'clingo version': re.compile(r'clingo version ([0-9\.]+)'),
        'libgringo': re.compile(r'libgringo version ([0-9\.]+)'),
        'libclasp': re.compile(r'libclasp version ([0-9\.]+)'),
        'libpotassco': re.compile(r'libpotassco version ([0-9\.]+)'),
        'python': re.compile(r'with[out]{0,3}\sPython\s?([0-9\.]+)?'),
        'lua': re.compile(r'with[out]{0,3}\sLua\s?([0-9\.]+)?'),
    }
    stdout = clingo.communicate()[0].decode()

    return {
        field: reg.search(stdout).groups()[0]
        for field, reg in fields.items()
    }


def _gen_answers(stdout:iter, stderr:iter, statistics:dict,
                 error_on_warning:bool) -> (str, int or None):
    """Yield 2-uplet (answer set, optimization),
    and update given statistics dict with statistics payloads

    """
    answer = None  # is used to generate a model only when we are sur there is (no) optimization
    for ptype, payload in parse_clasp_output(stdout, yield_stats=True):
        if ptype == 'answer':
            if answer is not None:
                yield answer, None  # no optimization to yield
            answer = payload
        elif ptype == 'optimization':
            if answer is not None:
                yield answer, payload
                answer = None
            else:
                assert False, "Optimization line without answer: " + repr(payload)
        elif ptype == 'statistics':
            statistics.update(payload)
        elif ptype == 'info':
            pass  # don't care
        else:
            assert ptype in parse_clasp_output.out_types, 'solving.parse_clasp_output yields an unexpceted type ' + repr(ptype)
    if answer is not None:  # if no optimization, probably one miss
        yield answer, None

    # handle stderr
    for payload in validate_clasp_stderr(stderr):
        if payload['level'] == 'error' and payload['message'].startswith('syntax error, '):
            raise ASPSyntaxError(
                payload['human message'][len('syntax error, '):],
                (payload['filename'], payload['lineno'],
                 payload['char_beg'], payload['text']),
                payload=payload)
        elif payload['level'] in {'warning', 'info'}:
            if error_on_warning:
                raise ASPWarning(payload['human message'], payload)
            else:
                pass  # do nothing, user said
        else:
            raise SystemError("Clingo yield a non-handled error " + repr(payload))
