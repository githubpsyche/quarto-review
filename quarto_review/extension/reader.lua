-- Defer Markdown parsing until the pre-ast filter has prepared review syntax.
-- Quarto still executes the manuscript first and supplies its metadata file.
Extensions = pandoc.format.extensions("markdown")
local readqmd = require("readqmd")

function Reader(inputs, options)
  local doc = pandoc.Pandoc({})
  doc.meta.quarto_pandoc_reader_opts = readqmd.options_to_meta(options)
  return doc
end
