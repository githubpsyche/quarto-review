// Independent schema validation; the input document is opened read-only.
using System.Text.Json;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;

if (args.Length == 0)
{
    Console.Error.WriteLine("Provide one or more DOCX paths.");
    return 2;
}

var reports = new List<object>();
var failures = 0;
foreach (var filename in args)
{
    using var document = WordprocessingDocument.Open(filename, false);
    var errors = new OpenXmlValidator(FileFormatVersions.Microsoft365)
        .Validate(document)
        .Select(error => new {
            description = error.Description,
            type = error.ErrorType.ToString(),
            part = error.Part?.Uri.ToString(),
            path = error.Path?.XPath
        }).ToArray();
    failures += errors.Length;
    reports.Add(new { file = filename, errors });
}
Console.WriteLine(JsonSerializer.Serialize(reports, new JsonSerializerOptions { WriteIndented = true }));
return failures == 0 ? 0 : 1;
