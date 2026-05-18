from app.services.gmaps_client import parse_gmaps_csv


def test_parse_gmaps_csv_preserves_rating_and_review_count():
    raw_csv = (
        "input_id,title,category,address,phone,website,link,rating,reviews_count\n"
        '1,Example Dental,Dentist,"123 Main St, Sioux Falls, SD, USA",'
        "555-0100,https://example.com,https://maps.example,4.7,\"1,234\"\n"
    )

    businesses = parse_gmaps_csv(raw_csv)

    assert len(businesses) == 1
    assert businesses[0].rating == 4.7
    assert businesses[0].review_count == 1234
