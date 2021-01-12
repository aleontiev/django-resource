from .expression import execute
from .utils import as_dict, cached_property
from .store import Store
from .exceptions import SchemaResolverError, ResourceMisconfigured


class Resource(object):
    class Schema:
        id = "resources"
        name = "resources"
        source = None
        description = "A complex API type composed of many fields"
        space = "."
        can = {"get": True, "inspect": True}
        parameters = None
        base = None
        features = None
        fields = {
            "id": {
                "primary": True,
                "type": "string",
                "description": "Identifies the resource within the server",
                "example": "resources",
            },
            "source": {
                "type": "any",
                "description": "Null, string, or object",
                "example": {
                    "source": "auth.user",
                    "where": {
                        "=": ["is_active", True]
                    }
                }
            },
            "url": {
                "type": "string",
                "source": {
                    "concat": [
                        'space.url',
                        'name',
                        "'/'",
                    ]
                },
                "can": {"set": False}
            },
            "name": {
                "type": "string",
                "description": "Identifies the resource within its space",
                "example": "resources",
            },
            "singleton": {
                "type": "boolean",
                "default": False,
                "description": ("Whether or not the resource represents one record"),
            },
            "description": {
                "type": ["null", "string"],
                "description": "Explanation of the resource",
            },
            "space": {
                "type": "@spaces",
                "inverse": "resources",
                "description": "The space containing the resource",
            },
            "fields": {
                "type": {
                    "type": "array",
                    "items": "@fields"
                },
                "inverse": "resource",
                "description": "The fields that make up the resource",
            },
            "can": {
                "type": {
                    "anyOf": [
                        {"type": "null"},
                        {"type": "array", "items": "string"},
                        {
                            "type": "object",
                            "additionalProperties": {
                                "type": ["null", "boolean", "object"]
                            }
                        },
                    ]
                },
                "description": "A map from action name to access rule",
                "example": {
                    "get": True,
                    "clone.record": {
                        "or": [{
                            "not": {
                                "<": ["updated", "created"]
                            }
                        }, {
                            "not.in": {
                                "location.name": ["'USA'", "'UK'"],
                            }
                        }]
                    },
                },
            },
            "parameters": {
                "type": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "type"
                    }
                },
                "description": "An object of custom input keys",
                "example": {
                    "clone.record": {"remap": {"is": "object", "of": "string"}}
                },
            },
            "bases": {
                "type": {
                    "type": "array",
                    "items": "@resources"
                },
                "inverse": "children",
                "description": "The parent resource",
            },
            "features": {
                "type": ["null", "object"],
                "description": "All features supported by this resource",
                "example": {
                    "page": {"max": 100},
                    "show": True,
                    "sort": True,
                    "where": False,
                },
            },
            "before": {
                "type": ["null", "object"],
                "description": "Map of pre-event handlers",
                "example": {
                    "delete": {
                        "verify": {
                            '.or': [{
                                ".request.user.id": {
                                    ".equals": "owner"
                                }
                            }, {
                                ".request.user.roles": {'contains': 'superuser'}
                            }]
                        },
                    }
                },
            },
            "after": {
                "type": ["null", "object"],
                "description": "Map of post-event handlers",
                "example": {
                    "get.record": {"webhook": "https://webhooks.io/example/"},
                    "add": {"increment": "creator.num_created"},
                },
            },
            "abstract": {
                "type": "boolean",
                "default": False
            },
        }

    def __repr__(self):
        return str(self)

    def __str__(self):
        id = self.get_id()
        return f"({self.__class__.__name__}: {id})"

    def __init__(self, **options):
        # make sure there is a schema and a name
        assert self.Schema.name is not None

        self._setup = False
        self._options = options
        self._fields = {}

    def __getattr__(self, key):
        if key.startswith("_"):
            return self.__dict__.get(key, None)

        return self.get_field(key).get_value()

    def __setattr__(self, key, value):
        if key.startswith("_"):
            return super(Resource, self).__setattr__(key, value)

        field = self.get_field(key)
        field.set_value(value)

    def _get_property(self, key):
        """Get field at given key (supporting.nested.paths)

        Raises:
            ValueError if key is not valid
        """
        if key is None:
            return self

        keys = [k for k in key.split(".") if k] if key else []
        value = self
        last = len(keys)
        if not last:
            this = str(self)
            raise ValueError(f"{key} is not a valid field of {this}")
        for i, key in enumerate(keys):
            is_last = i == last
            if key:
                field = value.get_field(key)
                if not is_last:
                    value = field.get_value()
        return field

    def add(self, key, value, index=None):
        return self._get_property(key).add_value(value, index=index)

    def get_property(self, key=None):
        return self._get_property(key).get_value(resolve=False, id=True)

    def get_option(self, key, default=None):
        if key in self._options:
            return self._options[key]
        else:
            if callable(default):
                # callable that takes self
                default = default(self)
            elif isinstance(default, dict):
                # expression that takes self
                default, _ = execute(default, self)
            return default

    @cached_property
    def data(self):
        return Store(self)

    @property
    def query(self):
        return self.data.query

    @classmethod
    def get_fields(cls):
        return cls.Schema.fields

    def get_field(self, key):
        from .field import Field

        fields = self.get_fields()
        if key not in self._fields:
            if key not in fields:
                this = str(self)
                raise AttributeError(f"{key} is not a valid field of {this}")

            field = fields[key]
            resolver = self.data.resolver
            # self.source: the model's source
            # schema: the field's source

            space = None
            if isinstance(field, str) or 'type' not in field:
                # may need self.space to resolve field type
                # for foreign key fields
                space = self.space

            source = self.get_meta('source')
            resource_id = self.get_meta('id')
            id = f"{resource_id}.{key}"

            try:
                field = resolver.get_field_schema(
                    source,
                    field,
                    space=space
                )
            except SchemaResolverError as e:
                exc = str(e)
                raise FieldMisconfigured(f'{id}: {exc}')

            self._fields[key] = Field.make(
                parent=self,
                resource=resource_id,
                id=id,
                name=key,
                **field
            )
        return self._fields[key]

    @classmethod
    def as_record(cls, **kwargs):
        id = cls.get_meta("id")
        fields = cls.get_fields()
        options = cls.get_meta()
        options["fields"] = ["{}.{}".format(id, key) for key in fields.keys()]
        for key, value in kwargs.items():
            options[key] = value
        return Resource(**options)

    def get_id_field(self):
        if getattr(self, "_id_field", None):
            return self._id_field

        for name, field in self.get_fields().items():
            if isinstance(field, dict) and field.get("primary", False):
                self._id_field = name
                return name

        raise ValueError(f"Resource {self.name} has no primary key")

    def get_id(self):
        id_field = self.get_id_field()
        return (
            getattr(self, id_field)
            if id_field in self._fields
            else self.get_option(id_field)
        )

    @classmethod
    def get_meta(cls, key=None, default=None):
        if not key:
            return as_dict(cls.Schema)
        return getattr(cls.Schema, key, default)

    def get_urlpatterns(self):
        """Get Django urlpatterns for this resource"""
        base = f'{self.space.server.url}/{self.space.name}/{self.name}'
        patterns = [base]
        for field in self.get_fields().keys():
            patterns.append(f'{base}/{field}')


def is_resolved(x):
    if isinstance(x, Resource):
        return True
    if isinstance(x, list) and all((isinstance(c, Resource) for c in x)):
        return True
    if isinstance(x, dict) and all((isinstance(c, Resource) for c in x.values())):
        return True
    return False
