---
 command: nomv
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/nomv
 title: nomv
 download_date: 2026-02-03 09:12:49
---

 # nomv

# nomv

## Description

Converts values of the specified multivalue field into one single value. Separates the values using a new line "\n delimiter.

Overrides the configurations for the multivalue field that are set in the fields.conf file.

## Syntax

nomv <field>

### Required arguments

Syntax: <field>

Description: The name of a multivalue field.

## Usage

The nomv command is a distributable streaming command. See Command types.

You can use evaluation functions and statistical functions on multivalue fields or to return multivalue fields.

## Examples

### Example 1:

For sendmail events, combine the values of the senders field into a single value. Display the top 10 values.

## See also
 