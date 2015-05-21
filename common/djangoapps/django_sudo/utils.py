"""
sudo.utils
"""


def region_name(region):
    """
    Replace special character's from region to make it valid for cookie name.

    region must be string or unicode.
    """
    char_to_be_replaced = [':', '/', '+']

    if region is not None:
        for char in char_to_be_replaced:
            region = region.replace(char, '-')

        region = region.encode('utf-8', 'ignore')

    return region
