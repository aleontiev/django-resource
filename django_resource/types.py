from .resource import Resource
from .exceptions import TypeValidationError


class Type(Resource):
    class Schema:
        id = "types"
        name = "types"
        space = "."
        fields = {
            "name": {"type": "string", "primary": True},
            "base": {"type": "@types", "inverse": "children"},
            "children": {
                "type": {"is": "array", "of": "@types"},
                "inverse": "base",
                "default": [],
            },
            "container": {"type": "boolean", "default": False},
            "server": {"type": "@server", "inverse": "types"},
        }

    @classmethod
    def get_base_type(cls, name, server=None):
        kwargs = {"name": name, "base": "any", "container": is_container(name)}
        if server:
            kwargs["server"] = server
        return cls(**kwargs)


arrays = {"array", "?array"}
unions = {"union", "?union"}
containers = {"union", "array", "map", "object", "option", "tuple"}


def is_list(T):
    if isinstance(T, str):
        return T in arrays
    elif isinstance(T, dict):
        return T["is"] in arrays or (
            T["is"] in unions and all([is_list(o) for o in T["of"]])
        )
    return False


def is_container(T):
    return T in containers


def is_link(T):
    if isinstance(T, str):
        return "@" in T
    elif isinstance(T, dict):
        type_of = T.get("of")
        return is_link(type_of) if type_of else None
    return False


def get_link(T):
    link = is_link(T)
    if link:
        return True, "".join(T[T.index("@") + 1 :])
    else:
        return None, None


def get_container(T):
    if isinstance(T, str):
        if T[0] == "?":
            return "option", T[1:]
        else:
            return None, None
    elif isinstance(T, dict):
        type_is = T["is"]
        type_of = T.get("of", None)
        if type_is[0] == "?":
            return "option", {"is": type_is[1:], "of": type_of}
        else:
            return T["is"], type_of


def validate(type, value):
    container, remainder = get_container(type)
    if container:
        expecting = None
        if container == "array":
            expecting = list
        elif container == "object":
            expecting = dict

        if expecting and not isinstance(value, expecting):
            raise TypeValidationError(f"expecting {container} but got: {value}")

        if remainder:
            # validate remainder
            if container == "array":
                return all((validate(remainder, v) for v in value))
            elif container == "object":
                return all((validate(remainder, v) for v in value.items()))
            elif container == "option":
                return (value is None) or validate(remainder, value)
            elif container == "union":
                # some type validations may throw exceptions
                # if any of them is valid
                for r in remainder:
                    try:
                        validate(r, value)
                    except TypeValidationError:
                        continue
                    return True
                raise TypeValidationError(f"could not match {type} to {value}")
        else:
            return True
    else:
        # base validation
        expecting = None
        if type == "number":
            expecting = (int, float)
        elif type == "string":
            expecting = str
        elif type == "any":
            expecting = None
        elif type == "boolean":
            expecting = bool
        elif type.startswith("@"):
            expecting = None

        if expecting and not isinstance(value, expecting):
            raise TypeValidationError(f"expecting {type} but got: {value}")

        return True
