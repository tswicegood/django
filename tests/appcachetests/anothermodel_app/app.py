from django import apps

class MyApp(apps.App):

    class Meta:
        models_path = 'model_app.othermodels'

class MyOtherApp(MyApp):

    class Meta:
        db_prefix = 'nomodel_app'
