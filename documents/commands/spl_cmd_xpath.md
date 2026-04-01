---
 command: xpath
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/xpath
 title: xpath
 download_date: 2026-02-03 09:21:29
---

 # xpath

Extracts the xpath value from field and sets the outfield attribute.

Note:  Due to limitations with XML extraction, the xpath command returns empty results when input XML strings have prologue headers, such as xml version or DOCTYPE. As a result, use the spath command instead of the xpath command when extracting XML content.

#### Syntax

xpath [outfield=<field>] <xpath-string> [field=<field>] [default=<string>]

#### Required arguments

#### Optional arguments

The xpath command is a distributable streaming command. See Command types.

The xpath command supports the syntax described in the Python Standard Library 19.7.2.2. Supported XPath syntax.

#### 1. Extract values from a single element in _raw XML events

You want to extract values from a single element in _raw XML events and write those values to a specific field.

The _raw XML events look like this:

Extract the nickname values from _raw XML events.  Output those values to the name field.

#### 2. Extract multiple values from _raw XML events

Extract multiple values from _raw XML events

The _raw XML events look like this:

Extract the values from the identity_id element from the _raw XML events:

This search returns two results: identity_id=3017669 and identity_id=1037669.

```
sname
```

```
instrument_id
```

Because you specify sname='BARC', this search returns one result: instrument_id=912383KM1.

#### 3. Testing extractions from XML events

You can use the makeresults command to test xpath extractions.

You must add field=xml to the end of your search. For example:

extract, kvform, multikv, rex, 
spath, xmlkv
 