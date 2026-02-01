from django import forms

class BaseModelForm(forms.ModelForm):
    
    class Meta:
        abstract = True
        exclude = [
            'created_at',
            'updated_at',
            'created_by',
            'updated_by',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Por si alguien los incluye en fields, los removemos:
        for f in ['created_at', 'updated_at', 'created_by', 'updated_by']:
            self.fields.pop(f, None)
