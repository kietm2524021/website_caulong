from django import forms

class UpdatePriceForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)

    PRICE_TYPE_CHOICES = (
        ('gia_thuong', 'Giá thường'),
        ('gia_vang', 'Giá vàng'),
        ('gia_co_dinh', 'Giá cố định'),
    )

    price_type = forms.ChoiceField(
        choices=PRICE_TYPE_CHOICES,
        label="Loại giá"
    )

    price_value = forms.IntegerField(
        label="Giá mới (nghìn đồng)",
        min_value=0,
        help_text="Ví dụ: nhập 80 = 80.000đ"
    )
