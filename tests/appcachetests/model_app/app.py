from django import apps

class MyApp(apps.App):

    class Meta:
        models_path = 'model_app.othermodels'

class MyOtherApp(MyApp):

    class Meta:
        db_prefix = 'nomodel_app'


class MySecondApp(MyOtherApp):

    class Meta:
        models_path = 'model_app.models'


class YetAnotherApp(apps.App):

    class Meta:
        models_path = 'model_app.yetanother'


class MyThirdApp(MySecondApp, YetAnotherApp):

    class Meta:
        pass
