from django import apps

class MyApp(apps.App):
    some_attribute = True

    class Meta:
        models_path = 'model_app.othermodels'

class MyOtherApp(MyApp):

    class Meta(MyApp.Meta):
        db_prefix = 'nomodel_app'


class MySecondApp(MyOtherApp):

    class Meta(MyOtherApp.Meta):
        models_path = 'model_app.models'


class YetAnotherApp(apps.App):

    class Meta:
        models_path = 'model_app.yetanother'


class MyThirdApp(YetAnotherApp, MySecondApp):

    class Meta(YetAnotherApp.Meta, MySecondApp.Meta):
        pass


class MyOverrideApp(MyOtherApp):

    pass

