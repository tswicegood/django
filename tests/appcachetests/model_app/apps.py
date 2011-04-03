from django.core.apps import App

class MyApp(App):
    def __init__(self, path):
        super(MyApp, self).__init__(path)
        self.models_path = 'model_app.othermodels'

class MyOtherApp(MyApp):
    def __init__(self, name):
        super(MyOtherApp, self).__init__(name)
        self.db_prefix = 'nomodel_app'
