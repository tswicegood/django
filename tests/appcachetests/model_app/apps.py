from django.core.apps import App

class MyApp(App):

    class Meta:
        models_path = 'model_app.othermodels'

class MyOtherApp(MyApp):

    class Meta:
        db_prefix = 'nomodel_app'
