from django.db import models

from .models import Schema
from .schema import get_schema

class MultiSchemaMixin(object):
    def from_schemata(self, *schemata):
        """
        Perform these queries across several schemata.
        """
        qs = getattr(self, 'get_queryset', self.get_query_set)()
        query = str(qs.query)
        
        if len(schemata) == 1 and hasattr(schemata[0], 'filter'):
            schemata = schemata[0]
        
        multi_query = [
            query.replace('FROM "', 'FROM "%s"."' % schema.schema) for schema in schemata
        ]
        
        return self.raw(" UNION ALL ".join(multi_query))

class MultiSchemaManager(MultiSchemaMixin, models.Manager):
    pass

class SchemaAware(object):
    _is_schema_aware = True
    
    def __init__(self, *args, **kwargs):
        super(SchemaAware, self).__init__(*args, **kwargs)
        # This doesn't work with MultiSchemaMixin-created object.
        if self.pk:
            self._schema = get_schema()
        else:
            self._schema = None
    
    def __eq__(self, other):
        return super(SchemaAware, self).__eq__(other) and self._schema == other._schema
    
    def save(self, *args, **kwargs):
        self._schema = get_schema()
        return super(SchemaAware, self).save(*args, **kwargs)

class SchemaAwareModel(SchemaAware, models.Model):
    """
    A Base class for models that should be in a seperate schema.
    """

    class Meta:
        abstract = True
    
