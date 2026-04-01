---
 command: kvform
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/kvform
 title: kvform
 download_date: 2026-02-03 09:10:21
---

 # kvform

Extracts key-value pairs from events based on a form template that describes how to extract the values.

Note: For Splunk Cloud Platform, you must create a private app to extract key-value pairs from events. If you are a Splunk Cloud administrator with experience creating private apps, see Manage private apps in your Splunk Cloud Platform deployment in the Splunk Cloud Admin Manual. If you have not created private apps, contact your Splunk account representative for help with this customization.

kvform [form=<string>] [field=<field>]

#### Optional arguments

Before you can use the kvform command, you must:

- Create the forms directory in the appropriate application path. For example $SPLUNK_HOME/etc/apps/<app_name>/forms.
- Create the .form files and add the files to the forms directory.

#### Format for the .form files

A .form file is essentially a text file of all static parts of a form. It might be interspersed with named references to regular expressions of the type found in the transforms.conf file.

An example .form file might look like this:

#### Specifying a form

If the form argument is specified, the kvform command uses the <form_name>.form file found in the Splunk configuration forms directory. For example, if form=sales_order, the kvform command looks for a sales_order.form file in the $SPLUNK_HOME/etc/apps/<app_name>/forms directory for all apps. All the events processed are matched against the form, trying to extract values.

#### Specifying a field

If you specify the field argument, the the kvform command looks for forms in the forms directory that correspond to the values for that field. For example, if you specify field=error_code, and an event has the field value error_code=404, the command looks for a form called 404.form in the $SPLUNK_HOME/etc/apps/<app_name>/forms directory.

#### Default value

If no form or field argument is specified, the kvform command uses the default value for the field argument, which is sourcetype. The kvform command looks for <sourcetype_value>.form files to extract values.

#### 1. Extract values using a specific form

Use a specific form to extract values from.

#### 2. Extract values using a field name

Specify field=sourcetype to extract values from forms such as splunkd.form and mongod.form. If there is a form for a source type, values are extracted from that form. If one of the source types is access_combined but there is no access_combined.form file, that source type is ignored.

#### 3. Extract values using the eventtype field
 