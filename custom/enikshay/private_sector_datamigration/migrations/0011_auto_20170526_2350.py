# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-05-26 23:50
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('private_sector_datamigration', '0010_episodeprescription'),
    ]

    operations = [
        migrations.AlterField(
            model_name='episodeprescription',
            name='episodeId',
            field=models.CharField(max_length=8, null=True),
        ),
    ]
