# -*- coding: utf-8 -*-
# Generated by Django 1.11.10 on 2018-02-08 11:39
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('linked_domain', '0005_migrate_linked_app_toggle'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='domainlinkhistory',
            options={'ordering': ('-date',)},
        ),
        migrations.AddField(
            model_name='domainlink',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='domainlink',
            name='last_pull',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='domainlink',
            name='remote_api_key',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='domainlink',
            name='remote_base_url',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='domainlink',
            name='remote_username',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='domainlinkhistory',
            name='model_detail',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
        ),
    ]
