---
 command: makemv
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/makemv
 title: makemv
 download_date: 2026-02-03 09:11:00
---

 # makemv

Converts a single valued field into a multivalue field by splitting the values on a string delimiter or by using a regular expression. The delimiter can be a multicharacter delimiter.

Note: The makemv command does not apply to internal fields.

See Use default fields in the Knowledge Manager Manual.

makemv [delim=<string> | tokenizer=<string>] [allowempty=<bool>] [setsv=<bool>] <field>

#### Required arguments

#### Optional arguments

The makemv command is a distributable streaming command. See Command types.

You can use evaluation functions and statistical functions on multivalue fields or to return multivalue fields.

#### 1. Use a comma to separate field values

For sendmail search results, separate the values of "senders" into multiple values. Display the top values.

#### 2. Use a colon delimiter and allow empty values

Separate the value of "product_info" into multiple values.

#### 3. Use a regular expression to separate values

The following search creates a result and adds three values  to the my_multival field.  The makemv command is used to separate the values in the field by using a regular expression.
 