# LLM-generated task-specific property checks — demo run

Model: `openai:gpt-4o-mini`
Tasks evaluated: 15
Total proposals compiled: 62
Accepted (discriminates good/bad): 22 (35.5%)
Rejected — trivially pass/fail: 31
Rejected — raises or bad return type: 9

## Example accepted checks
### `check_extracts_information` — from task `webmall.Webmall_Find_Specific_Product_Task1`
```python
def check_extracts_information(paths, code):
    extraction_needed = False
    for path in paths:
        for action in path:
            if action.func == 'search_on_page':
                extraction_needed = True
            if extraction_needed and action.func == 'extract_information_from_page':
                return PropertyResult(name='T3: Extracts information after searching', passed=True, message='Information is extracted after searching for the product.')
    return PropertyResult(name='T3: Extracts information after searching', passed=False, message='No information extraction found after searching for the product.')
```

### `check_opens_webshops` — from task `webmall.Webmall_Find_Specific_Product_Task2`
```python
def check_opens_webshops(paths, code):
    required_pages = ['http://localhost:8081', 'http://localhost:8082', 'http://localhost:8083', 'http://localhost:8084']
    opened_pages = set()
    for path in paths:
        for action in path:
            if action.func == 'open_page' and action.args[0] in required_pages:
                opened_pages.add(action.args[0])
    if opened_pages == set(required_pages):
        return PropertyResult(name='T1: All webshops are opened', passed=True, message='All required webshops have been opened.')
    return PropertyResult(name='T1: All webshops are opened', passed=False, message='Not all required webshops were opened.', counterexample=path)
```

### `check_fills_final_result` — from task `webmall.Webmall_Find_Specific_Product_Task3`
```python
def check_fills_final_result(paths, code):
    final_result_filled = any((a.func == 'fill_text_field' and 'Type your final answer here...' in a.args for path in paths for a in path))
    if not final_result_filled:
        return PropertyResult(name='T4: Fills final result before submission', passed=False, message='Final result is not filled into the text field before submission.')
    return PropertyResult(name='T4: Fills final result before submission', passed=True, message='Final result is filled into the text field before submission.')
```

### `check_fills_final_result` — from task `webmall.Webmall_Find_Specific_Product_Task4`
```python
def check_fills_final_result(paths, code):
    fill_text_field_found = False
    for path in paths:
        for action in path:
            if action.func == 'fill_text_field':
                fill_text_field_found = True
                break
    if fill_text_field_found:
        return PropertyResult(name='T4: Final result is filled in', passed=True, message='The final result has been filled into the text field.')
    return PropertyResult(name='T4: Final result is filled in', passed=False, message='No action found that fills the final result into the text field.')
```

### `check_opens_webshops` — from task `webmall.Webmall_Find_Specific_Product_Task5`
```python
def check_opens_webshops(paths, code):
    required_webshops = ['http://localhost:8081', 'http://localhost:8082', 'http://localhost:8083', 'http://localhost:8084']
    opened_webshops = set()
    for path in paths:
        for action in path:
            if action.func == 'open_page' and action.args[0] in required_webshops:
                opened_webshops.add(action.args[0])
    if opened_webshops == set(required_webshops):
        return PropertyResult(name='T1: All webshops are opened', passed=True, message='All required webshops have been opened.')
    return PropertyResult(name='T1: All webshops are opened', passed=False, message='Not all required webshops have been opened.', counterexample=path)
```

