import os
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path

from .problems import LKHProblem


class NoToursException(Exception):
    pass


def solve(solver='LKH', problem=None, **params):
    assert shutil.which(solver) is not None, f'{solver} not found.'
    assert ('problem_file' in params) ^ (problem is not None), 'Specify a problem object *or* a path.'

    if 'problem_file' in params:
        # annoying, but necessary to get the original problem dimension
        problem = LKHProblem.load(params['problem_file'])

    if not isinstance(problem, LKHProblem):
        warnings.warn('Subclassing LKHProblem is recommended. Proceed at your own risk!')

    if len(problem.depots) > 1:
        warnings.warn('LKH-3 cannot solve multi-depot problems.')

    prob_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
    problem.write(prob_file)
    prob_file.write('\n')
    prob_file.close()
    params['problem_file'] = prob_file.name

    # vanilla LKH does not support worker/output_directory; assume modified LKH use worker & output_directory to output the routs automatically, instead of parsing TOUR_FILE explicitly
    if "worker" not in params:
        params["worker"] = "lkh"
    if "output_directory" not in params:
        params["output_directory"] = tempfile.gettempdir()
    worker: str = str(params["worker"])
    output_directory: Path = Path(params["output_directory"])
    output_directory.mkdir(parents=True, exist_ok=True)
    par_path: Path = output_directory / f"{worker}.par"
    routes_path: Path = output_directory / f"{worker}.routes"

    par_file = tempfile.NamedTemporaryFile(mode='w+', delete=False)
    special = params.pop("special", False)
    if special is True:
        par_file.write("SPECIAL\n")
    for k, v in params.items():
        par_file.write(f'{k.upper()} = {v}\n')
    par_file.close()
    shutil.copy2(par_file.name, par_path)

    try:
        # stdin=DEVNULL for preventing a "Press any key" pause at the end of execution
        subprocess.check_output([solver, par_file.name], stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        raise Exception(e.output.decode())

    if not os.path.isfile(routes_path) or os.stat(routes_path).st_size == 0:
        raise NoToursException(f"{routes_path} does not appear to contain any tours. LKH probably did not find solution.")

    # the tour file produced by LKH-3 includes dummy nodes to indicate depots
    # for example, if a problem has DIMENSION=32 (1 depot node + 31 task nodes),
    # the tour file will have a SINGLE tour with DIMENSION=36 (5 depot nodes + 31 task nodes)
    solution = LKHProblem.load(routes_path)
    tour = solution.tours[0]
    # convert this tour to multiple routes
    routes = []
    route = []
    for node in tour:
        if node in problem.depots or node > problem.dimension:
            if len(route) > 0:
                routes.append(route)
            route = []
        else:
            route.append(node)
    routes.append(route)

    os.remove(par_file.name)
    if 'prob_file' in locals():
        os.remove(prob_file.name)

    return routes
