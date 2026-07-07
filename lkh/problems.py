from __future__ import annotations
import math
from pathlib import Path
import tsplib95 as tsplib

from tsplib95 import transformers, distances


distances.TYPES.update({
    'EXACT_2D': math.dist,
    'EXACT_3D': math.dist,
    'FLOOR_2D': distances.euclidean,
    'FLOOR_3D': distances.euclidean,
})


class NodeListField(tsplib.fields.TransformerField):
    default = list

    @classmethod
    def build_transformer(cls):
        node = transformers.FuncT(func=int)
        return transformers.ListT(value=node, terminal='-1')


class CTSPSetField(tsplib.fields.TransformerField):
    default = dict

    @classmethod
    def build_transformer(cls):
        salesman = transformers.FuncT(func=int)
        nodes = transformers.ListT(value=transformers.FuncT(func=int), terminal='-1')
        return transformers.MapT(key=salesman, value=nodes, sep='\n')


# demand can be multi-dimensional, for example in mPDTSP
class DemandsField(tsplib.fields.TransformerField):
    default = dict

    @classmethod
    def build_transformer(cls):
        node = transformers.FuncT(func=int)
        demand = transformers.ListT(value=transformers.FuncT(func=int))
        return transformers.MapT(key=node, value=demand, sep='\n')

    # we can only validate that the demands have the same dimensionality, not that it matches DEMAND_DIMENSION
    def validate(self, value):
        super().validate(value)
        dimensions = set(len(demand) for demand in value.values())
        if len(dimensions) > 1:
            error = ('all demands must have the same dimensionality '
                     f'but got multiple dimensions {dimensions}')
            raise tsplib.exceptions.ValidationError(error)


class LKHProblem(tsplib.models.StandardProblem):
    # extra spec fields
    demand_dimension = tsplib.fields.IntegerField('DEMAND_DIMENSION')
    distance = tsplib.fields.NumberField('DISTANCE')
    risk_threshold = tsplib.fields.IntegerField('RISK_THRESHOLD')
    salesmen = tsplib.fields.IntegerField('SALESMEN')
    scale = tsplib.fields.IntegerField('SCALE')
    service_time = tsplib.fields.NumberField('SERVICE_TIME')
    vehicles = tsplib.fields.IntegerField('VEHICLES')

    # extra data fields
    backhaul_section = NodeListField('BACKHAUL_SECTION')
    ctsp_set_section = CTSPSetField('CTSP_SET_SECTION')
    demand_section = DemandsField('DEMAND_SECTION') # draft limit has same unit as demand
    draft_limit_section = DemandsField('DRAFT_LIMIT_SECTION') # draft limit has same unit as demand
    pickup_and_delivery_section = tsplib.fields.MatrixField('PICKUP_AND_DELIVERY_SECTION')
    required_nodes_section = NodeListField('REQUIRED_NODES_SECTION')
    service_time_section = tsplib.fields.MatrixField('SERVICE_TIME_SECTION')
    time_window_section = tsplib.fields.MatrixField('TIME_WINDOW_SECTION')
    mtsp_objective = tsplib.fields.StringField('MTSP_OBJECTIVE')
    mtsp_min_size = tsplib.fields.IntegerField('MTSP_MIN_SIZE')
    mtsp_max_size = tsplib.fields.IntegerField('MTSP_MAX_SIZE')

    # need to override `render` because spec fields must precede data fields according to TSPLIB format
    # we assume that data fields end with _SECTION, and we sort those to the end of the field list
    # adapted from https://github.com/rhgrant10/tsplib95/blob/master/tsplib95/models.py#L217
    def render(self):
        # render each value by keyword
        rendered = self.as_name_dict()
        for name in list(rendered):
            value = rendered.pop(name)
            field = self.__class__.fields_by_name[name]
            if name in self.__dict__ or value != field.get_default_value():
                rendered[field.keyword] = field.render(value)

        # build keyword-value pairs with the separator
        kvpairs = []
        for keyword, value in sorted(rendered.items(), key=lambda item: item[0].endswith('_SECTION')):
            sep = ':\n' if '\n' in value else ': '
            kvpairs.append(f'{keyword}{sep}{value}')
        kvpairs.append('EOF')

        # join and return the result
        return '\n'.join(kvpairs)

    @classmethod
    def load_routes(cls, problem: LKHProblem, solution_path: Path) -> list[list[int]]:
        # the tour file produced by LKH-3 includes dummy nodes to indicate depots
        # for example, if a problem has DIMENSION=32 (1 depot node + 31 task nodes),
        # the tour file will have a SINGLE tour with DIMENSION=36 (5 depot nodes + 31 task nodes)
        if problem.type == "CVRP" and problem.depots != [1]:
            raise ValueError(f"LKH-3 does not support multi-depot CVRP problems, but got depots {problem.depots}")
        solution: LKHProblem = cls.load(solution_path)
        if not solution.type == "TOUR":
            raise ValueError(f"Expected solution file {solution_path} to be of type TOUR, but got {solution.type}")
        tour: list[int] = solution.tours[0]
        # convert this tour to multiple routes
        routes: list[list[int]] = []
        route: list[int] = []
        for node in tour:
            if node in problem.depots or node > problem.dimension:
                if len(route) > 0:
                    routes.append(route)
                route = []
            else:
                route.append(node)
        routes.append(route)

        # the above is the original implementation from __init__.py
        # we need to further process the routes to convert to 0-based indexing and validate TSP tours for pyvrp
        routes = [[node - 1 for node in route] for route in routes]  # convert to 0-based indexing, as pyvrp expects
        if problem.type == "TSP" and (first_node := routes[0].pop(0)) != 0:
            raise ValueError(f"Expected TSP tour to start with depot node 0, but got {first_node}")
        return routes
