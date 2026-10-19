.text
.global _ZN7android8NuPlayer14closeAudioSinkEv
.type _ZN7android8NuPlayer14closeAudioSinkEv, %function
_ZN7android8NuPlayer14closeAudioSinkEv:
    ldr x0, [x0, #8]
    ldr w1, [x0]
    add w1, w1, #1
    str w1, [x0]
    ret
.size _ZN7android8NuPlayer14closeAudioSinkEv, .-_ZN7android8NuPlayer14closeAudioSinkEv
.data
.p2align 12
.quad 0
.section .note.GNU-stack,"",%progbits
