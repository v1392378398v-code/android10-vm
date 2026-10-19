#ifndef A10VM_DEX_CLASS_INDEX_H
#define A10VM_DEX_CLASS_INDEX_H

#include "dex/dex_file.h"

namespace art {

const dex::ClassDef* FindIndexedClassDef(const DexFile& file, dex::TypeIndex type);
void ForgetClassIndex(const DexFile& file);

}  // namespace art

#endif
