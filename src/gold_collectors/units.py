"""Khối lượng chuẩn dùng chung khi đối chiếu vàng Việt Nam với giá quốc tế.

Một lượng bằng 37,5 gram, một chỉ bằng 3,75 gram và một troy ounce bằng
31,1034768 gram. Hệ số khoảng 1,205 là số ounce trong một lượng; không
được đưa thêm hệ số này vào bước đổi gram vì sẽ tính khối lượng hai lần.
"""

GRAMS_PER_LUONG = 37.5
GRAMS_PER_CHI = 3.75
GRAMS_PER_TROY_OUNCE = 31.1034768
CHI_PER_OZ = GRAMS_PER_TROY_OUNCE / GRAMS_PER_CHI
LUONG_PER_OZ = GRAMS_PER_TROY_OUNCE / GRAMS_PER_LUONG
OZ_PER_LUONG = GRAMS_PER_LUONG / GRAMS_PER_TROY_OUNCE
