from django.db import models

class Job(models.Model):
    name = models.CharField(max_length=30)

class Person(models.Model):
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    jobs = models.ManyToManyField(Job)

class Contact(models.Model):
    person = models.ForeignKey(Person)
