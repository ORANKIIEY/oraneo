import pandas as pd
import pytest
from src.validation import validate,read_csv,REQUIRED_COLUMNS
from src.generate_data import generate,CITIES,PRODUCTS


def valid_row(**kwargs):
    row={'order_id':'ZA-1','order_date':'21/10/2026','customer_id':'C-2','city':'  CAPE TOWN  ',
         'product':'  LAPTOP  ','quantity':'2','unit_price':'14999.00'}
    row.update(kwargs)
    return row

def test_south_african_synthetic_data():
    data=generate(250,seed=8)
    assert set(data['city'].dropna().str.title().unique()) <= set(CITIES)|{''}
    assert set(PRODUCTS).issuperset(data['product'].unique())
    assert not (data['city']=='Delhi').any()

def test_duplicate_valid_row_wins_over_invalid_first():
    result=validate(pd.DataFrame([valid_row(quantity='-1'),valid_row(quantity='2')]))
    assert result.input_count==2
    assert len(result.clean)==1 and len(result.duplicates)==1 and len(result.rejected)==0
    assert result.clean.iloc[0]['revenue']==29998
    assert result.duplicates.iloc[0]['disposition']=='duplicate_invalid'
    assert 'Invalid quantity' in result.duplicates.iloc[0]['reasons_json']

def test_duplicate_rows_with_no_valid_choice():
    result=validate(pd.DataFrame([valid_row(order_date='bad'),valid_row(quantity='NaN')]))
    assert len(result.clean)==0 and len(result.rejected)==1 and len(result.duplicates)==1

def test_invalid_ids_do_not_collapse_into_duplicates():
    result=validate(pd.DataFrame([valid_row(order_id=''),valid_row(order_id='')]))
    assert len(result.rejected)==2 and len(result.duplicates)==0

def test_multi_reason_on_single_rejected_row():
    result=validate(pd.DataFrame([valid_row(order_date='junk',city='',quantity='0',unit_price='oops')]))
    assert len(result.rejected)==1
    reasons=result.rejected.iloc[0]['reasons_json']
    for reason in ('Invalid order date','Missing city','Invalid quantity','Invalid unit price'):
        assert reason in reasons
    assert result.missing['city']==1

def test_revenue_precision_and_sa_date():
    result=validate(pd.DataFrame([valid_row(quantity='3',unit_price='199.99')]))
    row=result.clean.iloc[0]
    assert row['order_date']=='2026-10-21' and row['order_month']=='2026-10'
    assert row['city']=='Cape Town' and row['product']=='Laptop'
    assert row['revenue']==599.97

def test_broken_values_are_rejected():
    for kwargs in [dict(order_date='2026-02-31'),dict(customer_id=';drop'),
                   dict(order_id='a a'),dict(quantity='1.1'),dict(quantity='Infinity'),
                   dict(unit_price='-2'),dict(unit_price='0'),dict(unit_price='1e3000'),
                   dict(unit_price='5.999'),dict(city=' '),dict(product=' ')]:
        result=validate(pd.DataFrame([valid_row(**kwargs)]))
        assert len(result.clean)==0,kwargs

def test_revenue_overflow_rejected():
    result=validate(pd.DataFrame([valid_row(quantity='999999999999',unit_price='900')]))
    assert 'Revenue overflow' in result.rejected.iloc[0]['reasons_json']

def test_missing_required_columns(tmp_path):
    path=tmp_path/'missing.csv';pd.DataFrame([{'city':'Cape Town'}]).to_csv(path,index=False)
    with pytest.raises(ValueError,match='Missing required columns'):read_csv(str(path))

def test_empty_and_malformed_file(tmp_path):
    p=tmp_path/'empty.csv';p.write_text('');
    with pytest.raises(ValueError,match='empty'):read_csv(str(p))
    p.write_text(','.join(REQUIRED_COLUMNS)+'\n')
    with pytest.raises(ValueError,match='no data rows'):read_csv(str(p))
    p.write_text(','.join(REQUIRED_COLUMNS)+'\n"unterminated,1,2,3,4,5,6\n')
    with pytest.raises(ValueError,match='Invalid CSV'):read_csv(str(p))
