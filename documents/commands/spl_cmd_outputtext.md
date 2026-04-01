---
 command: outputtext
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/outputtext
 title: outputtext
 download_date: 2026-02-03 09:13:32
---

 # outputtext

# outputtext

## Description

Outputs the contents of the  _raw field to the _xml field.

The outputtext command was created as an internal mechanism to render event texts for output.

## Syntax

outputtext [usexml=<bool>]

### Optional arguments

Syntax: usexml=<bool>

Description: If set to true, the copy of the _raw field in the _xml is escaped XML.  If usexml is set to false, the _xml field is an exact copy of _raw.

Default: true

## Usage

The outputtext command is a reporting command.

The outputtext command writes all search results to the search head. In Splunk Web, the results appear in the Statistics tab.

## Examples

### 1. Output the _raw field into escaped XML

Output the "_raw" field of your current search into "_xml".

## See also
 