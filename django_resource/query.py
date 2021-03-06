from collections import defaultdict
from urllib.parse import parse_qs
from .utils import merge as _merge
from copy import deepcopy
from .exceptions import QueryValidationError, QueryExecutionError
from .features import (
    get_feature,
    get_feature_separator,
    get_take_fields,
    get_sort_fields,
    NestedFeature,
    WHERE,
    TAKE,
    SORT,
)
from .boolean import (
    build_expression,
    BOOLEAN_OPERATORS,
    SIMPLE_EXPRESSIONS
)


def coerce_query_value(value, singletons=True):
    """Try to coerce to boolean, null, integer, float"""
    if singletons:
        # coerce to singleton values: boolean/null

        lower = value.lower()
        if lower == 'true':
            return True

        if lower == 'false':
            return False

        if lower == 'null':
            return None

    try:
        value = int(value)
    except ValueError:
        pass
    else:
        return value

    try:
        value = float(value)
    except ValueError:
        pass
    else:
        return value

    return value


def coerce_query_values(values, singletons=True):
    single = isinstance(values, list) and len(values) == 1
    values = [coerce_query_value(value, singletons) for value in values]
    return values[0] if single else values


class Query(object):
    # methods
    def __init__(self, state=None, executor=None):
        """
        Arguments:
            state: internal query representation
        """
        self._state = state or {}
        self.executor = executor

    def add(self, record=None, field=None):
        return self._call('add', record=record, field=field)

    def set(self, record=None, field=None):
        return self._call('set', record=record, field=field)

    def get(self, record=None, field=None):
        return self._call('get', record=record, field=field)

    def edit(self, record=None, field=None):
        return self._call('edit', record=record, field=field)

    def delete(self, record=None, field=None):
        return self._call('delete', record=record, field=field)

    def options(self, record=None, field=None):
        return self._call('options', record=record, field=field)

    def execute(self, **kwargs):
        executor = self.executor
        if not executor:
            raise QueryExecutionError(f'Query cannot execute without executor')
        method_name = self.state.get('method', 'get')
        method = getattr(self.executor, method_name, None)
        if not method:
            raise QueryValidationError(f'Invalid method {method_name}')
        return method(self, **kwargs)

    @property
    def state(self):
        return self._state

    # features

    def body(self, body):
        return self._update({"body": body})

    def record(self, name):
        return self._update({"record": name})

    def field(self, name):
        return self._update({"field": name})

    def method(self, name):
        return self._update({"method": name})

    @property
    def take(self):
        return NestedFeature(self, "take")

    @property
    def where(self):
        return NestedFeature(self, "where")

    @property
    def sort(self):
        return NestedFeature(self, "sort")

    @property
    def group(self):
        return NestedFeature(self, "group")

    def inspect(self, args=None, copy=True, **kwargs):
        """
        Example:
            .inspect(resource=True)
        """
        if args:
            kwargs = args

        return self._update({"inspect": kwargs}, copy=copy, merge=True)

    def page(self, args=None, copy=True, **kwargs):
        """
        Example:
            .page(key='abcdef123a==')
        """
        if args:
            kwargs = args

        return self._update({"page": kwargs}, copy=copy, merge=True)

    def _take(self, level, *args, copy=True):
        kwargs = {}
        for arg in args:
            show = True
            if arg.startswith('-'):
                arg = arg[1:]
                show = False
            kwargs[arg] = show
        return self._update({'take': kwargs}, copy=copy, level=level, merge=True)

    def _call(self, method, record=None, field=None):
        if self.state.get('method') != method:
            return getattr(self.method(method), method)(
                record=record, field=field
            )

        if record or field:
            # redirect back through copy
            args = {}
            if record:
                args['record'] = record
            if field:
                args['field'] = field
            return getattr(self._update(args), method)()

        return self.execute()

    def _where(self, level, query, copy=True):
        """
        Example:
            .where({
                'or': [
                    {'contains': ['users.location.name', '"New York"']},
                    {'not': {'in': ['users', [1, 2]]}}
                ]
            })
        """
        return self._update({"where": query}, copy=copy, level=level)

    def _sort(self, level, *args, copy=True):
        """
        Example:
            .sort("name", "-created")
        """
        return self._update({"sort": args}, copy=copy, level=level)

    def _group(self, level, args=None, copy=True, **kwargs):
        """
        Example:
            .group({"count": {"count": "id"})
        """
        if args:
            kwargs = args

        return self._update(
            {"group": kwargs},
            copy=copy,
            level=level,
            merge=True
        )

    def __str__(self):
        return str(self.state)

    def _update(self, args=None, level=None, merge=False, copy=True, **kwargs):
        if args:
            kwargs = args

        state = None
        if copy:
            state = deepcopy(self.state)
        else:
            state = self.state

        sub = state
        # adjust substate at particular level
        # default: adjust root level
        take = 'take'
        if level:
            for part in level.split("."):
                if take not in sub:
                    sub[take] = {}

                fields = sub[take]
                try:
                    new_sub = fields[part]
                except KeyError:
                    fields[part] = {}
                    sub = fields[part]
                else:
                    if isinstance(new_sub, bool):
                        fields[part] = {}
                        sub = fields[part]
                    else:
                        sub = new_sub

        for key, value in kwargs.items():
            if merge and isinstance(value, dict) and sub.get(key):
                # deep merge
                _merge(value, sub[key])
            else:
                # shallow merge, assign the state
                sub[key] = value

        if copy:
            return Query(state=state)
        else:
            return self

    def __getitem__(self, key):
        return self._state[key]

    @classmethod
    def _update_where(cls, query, leveled):
        for level, wheres in leveled.items():
            expression = 'and'
            operands = {}
            for i, where in enumerate(wheres):
                num_parts = len(where)
                with_level = f'.{level}' if level else ''
                separator = ':'
                with_remainder = separator + separator.join(where[:-1]) if num_parts > 1 else ''
                original = f"where{with_level}{with_remainder}"
                key = operand = None
                if num_parts == 1:
                    # where=a and b
                    value = where[0]
                    if len(value) > 1:
                        value = ', '.join(value)
                        raise QueryValidationError(
                            f'Invalid where key "{original}", multiple values provided'
                        )
                    value = value[0]
                    expression = value
                elif num_parts == 2:
                    # where:name=Joe
                    # -> {"name": "Joe"}
                    operand = {
                        '=': [where[0], coerce_query_values(where[1], singletons=False)]
                    }
                    key = str(i)
                elif num_parts == 3:
                    # where:name:equals=Joe
                    # -> {"equals": ["name", "Joe"]}}
                    operand = {
                        where[1]: [where[0], coerce_query_values(where[2], singletons=False)]
                    }
                    key = str(i)
                elif num_parts == 4:
                    # where:name:equals:tag=Joe
                    operand = {
                        where[1]: [
                            where[0], coerce_query_values(where[3], singletons=False)
                        ]
                    }
                    key = where[2]
                    if key in BOOLEAN_OPERATORS:
                        raise QueryValidationError(
                            f'Invalid where key "{original}", using operator "{key}"'
                        )
                else:
                    raise QueryValidationError(
                        f'Invalid where key "{original}", too many segments'
                    )
                if operand and key:
                    if key in operands:
                        raise QueryValidationError(
                            f'Invalid where keys, duplicate tags for "{key}"'
                        )
                    operands[key] = operand

            values = list(operands.values())
            if expression not in SIMPLE_EXPRESSIONS:
                # expression specified, try to build it
                update = build_expression(expression, operands)
            else:
                # no expression given, implicit AND
                if len(values) == 1:
                    # simplest case: just one condition
                    update = values
                else:
                    # many conditions
                    update = {expression: values}

            update = {'where': update}
            query._update(
                update,
                level=level,
                merge=False,
                copy=False
            )

    @classmethod
    def _build_update(cls, parts, key, value):
        update = {}
        num_parts = len(parts)
        if not key:
            update = value
        elif num_parts:
            update[key] = {}
            current = update[key]
            for i, part in enumerate(parts):
                if i != num_parts - 1:
                    current = current[part] = {}
                else:
                    current[part] = value

        else:
            update[key] = value
        return update

    @classmethod
    def from_querystring(cls, value, **kwargs):
        result = cls(**kwargs)
        query = parse_qs(value)
        where = defaultdict(list)  # level -> [args]
        for key, value in query.items():
            feature = get_feature(key)
            separator = get_feature_separator(feature)

            # determine level
            parts = key.split(separator)
            feature_part = parts[0]

            level = None
            if '.' in feature_part:
                level = '.'.join(feature_part.split('.')[1:])
                if not level:
                    level = None

            parts = parts[1:]

            # handle WHERE separately because of special expression parsing
            # that can join together multiple conditions
            if feature == WHERE:
                parts.append(value)
                where[level].append(parts)
                continue

            # coerce value based on feature name
            update_key = feature
            if feature == TAKE:
                value = get_take_fields(value)
            elif feature == SORT:
                value = get_sort_fields(value)
            else:
                value = coerce_query_values(value)

            update = cls._build_update(parts, update_key, value)
            result._update(
                update,
                level=level,
                merge=feature != SORT,
                copy=False
            )
        if where:
            cls._update_where(result, where)

        return result
