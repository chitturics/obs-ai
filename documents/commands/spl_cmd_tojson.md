---
 command: tojson
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/tojson
 title: tojson
 download_date: 2026-02-03 09:19:27
---

 # tojson

Converts events into JSON objects. You can specify which fields get converted by identifying them through exact match or through wildcard expressions. You can also apply specific JSON datatypes to field values using datatype functions. The tojson command converts multivalue fields into JSON arrays.

When fields are specifically named in a tojson search, the command generates JSON objects that are limited to the values of just those named fields. If no fields are specified for tojson, tojson generates JSON objects for all fields that would otherwise be returned by the search.

Required syntax is in bold.

#### Optional arguments

The tojson command is a streaming command, which means it operates on each event as it is returned by the search. See Types of commands.

#### Apply JSON datatypes to field values

The tojson command applies JSON datatypes to field values according to logic encoded in its datatype functions.

You can assign specific datatype functions to fields when you write a tojson search. Alternatively, you can name a set of fields without associating them with datatype functions, and then identify a default_type that tojson can apply to those unaffiliated fields.

If you do not specify any fields for the tojson command, the tojson returns JSON objects for each field that can possibly be returned by the search at that point, and applies the none datatype function to the values of those fields. The none datatype function applies the numeric datatype to field values that are purely numeric, and applies the string datatype to all other field values.

The following table explains the logic that the various datatype functions use to apply datatypes to the values of the fields with which they are associated.

| Datatype function | Conversion logic |
| --- | --- |
| auto | Converts all values of the specified field into JSON-formatted output. Automatically determines the field datatypes.
If the value is numeric, the JSON output has a numeric output and includes a literal numeric.If the value is the string true or false the JSON output has a Boolean type.If the value is a literal null, , the JSON output has a null type and includes a null value.If the value is a string other than the previously mentioned strings, tojson examines the string. If it is proper JSON, tojson outputs a nested JSON object. If it is not proper JSON, tojson includes the string in the output. |
| bool | Converts valid values of the specified field to the Boolean datatype, and skips invalid values, using string validation.
If the value is a number, tojson outputs false only if that value is 0. Otherwise tojson outputs false.If the value is a string, tojson outputs false only if the value is false, f, or no.The tojson processor outputs true only if the value is code true, t, or yes. If the value does not fit into those two sets of strings, it is skipped.The validation for the bool datatype function is case insensitive. This means that it also interprets FALSE, False, F, and NO as false. |
| json | Converts all values of the specified field to the JSON type, using string validation. Skips values with invalid JSON.
If the value is a number, tojson outputs that number.If the value is a string, tojson outputs the string as a JSON block.If the value is invalid JSON, tojson skips it. |
| none | Outputs all values for the specified field in the JSON type. Does not apply string validation.
If the value is a number, tojson outputs a numeric datatype in the JSON block.If the value is a string, tojson outputs a string datatype. |
| num | Converts all values of the specified field to the numeric type, using string validation.
If the value is a number, tojson outputs that value and gives it the numeric datatype.If the value is a string, tojson attempts to parse the string as a number. If it cannot, it skips the value. |
| str | Converts all values of the specified field into the string datatype, using string validation. The tojson processor applies the string type to all values of the specified field, even if they are numbers, Boolean values, and so on. |

When a field includes multivalues, tojson outputs a JSON array and applies the datatype function logic to each element of the array.

#### 1. Convert all events returned by a search into JSON objects

#### 2. Specify different datatypes for 'date' fields

#### 3. Limit JSON object output and apply datatypes to the field values

#### 4. Convert all events into JSON objects and apply appropriate datatypes to all field values

#### 5. Apply the Boolean datatype to a specific field

#### 6. Include internal fields and assign a 'null' value to skipped fields

#### 7. Designate a default datatype for a set of fields and write the JSON objects to another field
 