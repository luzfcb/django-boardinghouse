import os

import django
from django.conf import settings
from django.core.cache import cache
from django.db import models, connection
from django.utils.translation import ugettext_lazy as _

import signals

global _active_schema

class Forbidden(Exception):
    """
    An exception that will be raised when an attempt to activate a non-valid
    schema is made.
    """

class TemplateSchemaActivation(Forbidden):
    """
    An exception that will be raised when a user attempts to activate
    the __template__ schema.
    """
    def __init__(self, *args, **kwargs):
        super(TemplateSchemaActivation, self).__init__(
            'Activating template schema forbidden.', *args, **kwargs
        )


def get_schema_model():
    return models.get_model('boardinghouse','schema')

_active_schema = None

def _get_search_path():
    cursor = connection.cursor()
    cursor.execute('SHOW search_path')
    search_path = cursor.fetchone()[0]
    cursor.close()
    return search_path.split(',')
    
    
def get_active_schema_name():
    """
    Get the currently active schema.
    
    This requires a database query to ask it what the current `search_path` is.
    """
    global _active_schema
    
    if _active_schema:
        return _active_schema
    
    reported_schema = _get_search_path()[0]
    
    if _get_schema(reported_schema):
        _active_schema = reported_schema
    else:
        _active_schema = None
    
    return _active_schema

def get_active_schema():
    """
    Get the (internal) name of the currently active schema.
    """
    return _get_schema(get_active_schema_name())

def get_active_schemata():
    """
    Get a (cached) list of all currently active schemata.
    """
    schemata = cache.get('active-schemata')
    if schemata is None:
        schemata = get_schema_model().objects.active()
        cache.set('active-schemata', schemata)
    return schemata

def _get_schema(schema_name):
    """
    Get the matching active schema object for the given name,
    if it exists.
    """
    if not schema_name:
        return
    for schema in get_active_schemata():
        if schema_name == schema.schema:
            return schema
        if schema_name == schema:
            return schema

def activate_schema(schema_name):
    """
    Activate the current schema: this will execute, in the database
    connection, something like:
    
        SET search_path TO "foo",public;
        
    It sends signals before and after that the schema will be, and was
    activated.
    
    Must be passed a string: the internal name of the schema to activate.
    """
    if schema_name == '__template__':
        raise TemplateSchemaActivation()
    
    global _active_schema
    cursor = connection.cursor()
    signals.schema_pre_activate.send(sender=None, schema_name=schema_name)
    cursor.execute('SET search_path TO %s,public;' % schema_name)
    signals.schema_post_activate.send(sender=None, schema_name=schema_name)
    _active_schema = schema_name
    cursor.close()

def activate_template_schema():
    """
    Activate the template schema. You probably don't want to do this.
    """
    global _active_schema
    _active_schema = None
    schema_name = '__template__'
    cursor = connection.cursor()
    signals.schema_pre_activate.send(sender=None, schema_name=schema_name)
    cursor.execute('SET search_path TO %s,public;' % schema_name)
    signals.schema_post_activate.send(sender=None, schema_name=schema_name)

def get_template_schema():
    return get_schema_model()('__template__')

def deactivate_schema(schema=None):
    """
    Deactivate the provided (or current) schema.
    """
    global _active_schema
    cursor = connection.cursor()
    signals.schema_pre_activate.send(sender=None, schema_name=None)
    cursor.execute('SET search_path TO "$user",public;')
    signals.schema_post_activate.send(sender=None, schema_name=None)
    _active_schema = None
    cursor.close()

#: These models are required to be shared by the system.
REQUIRED_SHARED_MODELS = [
    'auth.user',
    'auth.permission',
    'auth.group',
    'sites.site',
    'sessions.session',
    'contenttypes.contenttype',
    'admin.logentry',
    'south.migrationhistory',
    'migrations.migration',
]

def _is_join_model(model):
    return all([
        (field.primary_key or field.rel)
        for field in model._meta.fields
    ])

def is_shared_model(model):
    """
    Is the model (or instance of a model) one that should be in the
    public/shared schema?
    """
    if model._is_shared_model:
        return True
    
    if django.VERSION < (1, 6):
        app_model = '%s.%s' % (
            model._meta.app_label,
            model._meta.object_name.lower()
        )
    else:
        app_model = '%s.%s' % (
            model._meta.app_label, 
            model._meta.model_name
        )
    
    if app_model in REQUIRED_SHARED_MODELS:
        return True
    
    if app_model in settings.SHARED_MODELS:
        return True
    
    # if all fields are auto or fk, then we are a join model,
    # and if all related objects are shared, then we must
    # also be shared.
    if _is_join_model(model):
        return all([
            is_shared_model(field.rel.get_related_field().model)
            for field in model._meta.fields if field.rel
        ])
    
    return False

def is_shared_table(table):
    """
    Is the model from the provided database table name shared?
    
    We may need to look and see if we can work out which models
    this table joins.
    """
    # Get a mapping of all table names to models.
    table_map = dict([
        (x._meta.db_table, x) for x in models.get_models()
        if not x._meta.proxy
    ])
    
    # If we have a match, see if that one is shared.
    if table in table_map:
        return is_shared_model(table_map[table])
    
    # It may be a join table.
    prefixes = [
        (db_table, model) for db_table, model in table_map.items()
        if table.startswith(db_table)
    ]
    
    if len(prefixes) == 1:
        db_table, model = prefixes[0]
        rel_model = model._meta.get_field_by_name(
            table.replace(db_table, '').lstrip('_')
        )[0].rel.get_related_field().model
    
    return is_shared_model(model) and is_shared_model(rel_model)
    
## Internal helper functions.

def _install_clone_schema_function():
    """
    A large part of this project is based around how simple it is to
    clone a schema's structure into a new schema. This is encapsulated in
    an SQL script: this function will install that function into the current
    database.
    """
    clone_schema_file = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'sql', 'clone_schema.sql')
    clone_schema_function = " ".join([x.strip() for x in open(clone_schema_file).readlines() if not x.strip().startswith('--')])
    clone_schema_function = clone_schema_function.replace("%", "%%")
    cursor = connection.cursor()
    cursor.execute(clone_schema_function)
    cursor.close()

def _wrap_command(command):
    def inner(self, *args, **kwargs):
        _install_clone_schema_function()
        get_template_schema().create_schema()
        
        cursor = connection.cursor()
        cursor.execute('SET search_path TO public,__template__;')
        cursor.close()
        
        command(self, *args, **kwargs)
        
        deactivate_schema()
        
        # We don't want just active schemata...
        for schema in get_schema_model().objects.all():
            schema.create_schema()
    
    return inner