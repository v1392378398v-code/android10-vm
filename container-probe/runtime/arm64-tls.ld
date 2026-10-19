SECTIONS {
  .tdata : ALIGN(64) { *(.tdata .tdata.* .gnu.linkonce.td.*) }
}
INSERT BEFORE .tbss;
