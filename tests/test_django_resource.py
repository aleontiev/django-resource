from django.test import TestCase
from django_resource import __version__
from django_resource.space import Space
from django_resource.resource import Resource
from django_resource.server import Server




class IntegrationTestCase(TestCase):
    def test_version(self):
        self.assertEqual(__version__, '0.1.0')

    def test_social_network(self):
        # social network integration setup
        # one space: test
        # three collections:
        # - users (auth.user)
        # - groups (auth.group)
        # - posts (custom model with a creator and a group)
        # one singleton:
        # - session (for authentication)

        # 1. login
        # Request:
        #     POST /api/test/session?take.user=id,name,email {"username": "test", "password": "test"}
        # Success:
        #     201 {
        #       "data": {
        #           "user": {
        #               "id": 1234,
        #               "name": "Joe Smith",
        #               "email": "joe@smith.com"
        #           }
        #       }
        #     }
        # Failure:
        #     403 {
        #       "errors": {
        #           "body": {
        #               "password": "invalid password provided"
        #           }
        #       }
        #     }
        #     400 {
        #       "errors": {
        #           "query": {
        #               "take.user": {"name": "invalid field"}
        #           }
        #       }
        #     }

        # 2a. view user ID only
        # Request:
        #     GET /api/test/session/user
        # Success:
        #     200 {
        #       "data": 1234
        #     }

        # 2a. view user details
        # Request:
        #     GET /api/test/session/user/?take=id,name,groups
        # Success:
        #     200 {
        #       "data": {
        #           "id": 1234,
        #           "name": "John",
        #           "groups": [
        #               1, 2, 3, 4, 5
        #           ]
        #       },
        #     }

        # 2b. change name
        # Request:
        #     PATCH /api/test/users/1234 {"name": "Jim"}
        # Success:
        #     200 {
        #       "data": {
        #           "id": 1234,
        #           "name": "Jim",
        #           "updated": "2020-01-01T00:00:00Z"
        #       },
        #     }

        # 2c. change password
        # Request:
        #     POST /api/test/users/1234?method=change-password {"old_password": "123", "new_password": "asd", "confirm_password": "asd"}
        # Success:
        #     200 {"data": "ok"}
        # Failure:
        #     400 {
        #       "errors": {
        #           "body": {
        #               "old_password": ["this field is required"],
        #               "confirm_password": ["does not match new password"],
        #               "new_password": ["must have at least one symbol"]
        #           }
        #        }
        #     }
        #     400 {
        #       "errors": {
        #           "data": {
        #               "session": {
        #                   "old_password": [
        #                       "incorrect password"
        #                   ]
        #               }
        #           }
        #        }
        #     }

        # 3. list users, groups, and users in groups
        # Request:
        #     GET /api/test/?take.users=id,name&take.groups=id,name&take.groups.users=id,name
        # Success:
        #     200 {
        #         "data": {
        #             "users": [{
        #               "id": 1,
        #               "name": "Joe"
        #             }, ...],
        #             "groups": [{
        #               "id": 1,
        #               "users": [{
        #                   "id": 1,
        #                   "name": "Joe",
        #               }, ...]
        #             }]
        #         },
        #         "meta": {
        #             "page": {
        #                 "data.users": {
        #                   "next": "/api/test?take.users=id,name&page.users:cursor=ABCDEF"
        #                   "records": 1000
        #                 },
        #                 "data.groups": {
        #                   "next": "/api/test?take.groups.users=id,name&take.groups=id,name&page.groups:cursor=ABCDEF"
        #                   "records": 1000
        #                 },
        #                 "data.groups.0.users": {
        #                   "next": "/api/test/groups/0/users?take=id,name&page:cursor=ABCDEF"
        #                 }
        #             }
        #         }
        #     }

        server = Server(
            url='http://localhost/api',
        )
        test = Space(name='test', server=server)

        def login(resource, request, query):
            api_key = query.state('body').get('api_key')
            api_key = json.loads(str(base64.b64decode(api_key)))
            if authenticate(username, password):
                pass

        def logout(resource, request, query):
            pass

        def change_password(resource, request, query):
            pass

        session = Resource(
            id='test.session',
            name='session',
            singleton=True,
            can={
                'login': True,
                'logout': True,
                'add': False,
                'set': False,
                'edit': False,
                'delete': False
            },
            fields={
                "user": {
                    "type": ["null", "@users"],
                    "source": ".request.user_id"
                },
                "username": {
                    "type": "string",
                    "can": {"login": True, "get": False}
                },
                "password": {
                    "type": "string",
                    "can": {"login": True, "get": False}
                }
            },
            methods={
                'login': login,
                'logout': logout
            }
        )

        users = Resource(
            id='test.users',
            name='users',
            source='auth.user',
            space=test,
            fields={
                'id': 'id',
                'first_name': 'first_name',
                'last_name': 'last_name',
                'name': {
                    'source': {
                        'join': {
                            'items': [
                                {
                                    'case': [{
                                        'when': {
                                            '=': ['gender', '"male"'],
                                        },
                                        'then': '"Mr."'
                                    }, {
                                        'when': {
                                            '=': ['gender', '"female"'],
                                        },
                                        'then': '"Mrs."'
                                    }, {
                                        'else': ''
                                    }]
                                },
                                'first_name',
                                'last_name'
                            ],
                            'separator': ' '
                        }
                    },
                    'can': {
                        'set': False,
                        'delete': False
                    }
                },
                'email': 'email',
                'groups': {
                    'inverse': 'users',
                    'lazy': True,
                    'can': {
                        'set': False,
                        'delete': False
                    }
                },
            },
            can={
                'get': {
                    'or': [{
                        '=': [
                            'id', 'request.user_id'
                        ]
                    }, {
                        'in': [
                            'request.user_id', 'users'
                        ]
                    }, {
                        '=': ['request.is_superuser', True]
                    }]
                },
                'inspect': True,
                'add': {'=': ['request.is_superuser', True]},
                'set': {'=': ['request.is_superuser', True]},
                'edit': {'=': ['request.is_superuser', True]},
                'delete': {'=': ['request.is_superuser}', True]},
                'change-password': {'=': ['id', 'request.user_id']}
            },
            parameters={
                'change-password': {
                    'old_password': {
                        'type': 'string',
                    },
                    'new_password': {
                        'type': {
                            'type': 'string',
                            'min_length': 10,
                        }
                    },
                    'confirm_password': {
                        'type': 'string',
                    }
                }
            },
            before={
                'change-password': {
                    'check': {
                        '=': [
                            'confirm_password',
                            'new_password'
                        ]
                    }
                }
            },
            methods={
                'change-password': change_password,
            }
        )
        self.assertEqual(users.id, 'test.users')
        self.assertEqual(users.space.name, 'test')
        self.assertEqual(users.space, test)

        query1 = test.data.query('users?take=id,name&page.size=10&method=get')
        query2 = (
            test.data.query
            .resource('users')
            .take('id', 'name')
            .page(size=10)
            .method('get')
        )
        self.assertEqual(query1.state, query2.state)

        query3 = test.data.query(
            '?take.users=id,name&page.size=10&take.groups=id'
        )
        query4 = (
            test.data.query
            .take.users('id', 'name')
            .take.groups('id')
            .page(size=10)
        )
        self.assertEqual(query3.state, query4.state)

        context = {
            'request': {
                'user': {
                    'id': '1',
                    'is_superuser': True
                }
            }
        }
