/* MSVC compatibility shim, force-included (cl /FI) for the win_arm64 build.
 *
 * The upstream win_amd64 / linux wheels are compiled with mingw-gcc or clang,
 * which understand GCC attributes. python/message.c uses an unguarded
 * __attribute__((flatten)) (an optimization hint only). Native MSVC cl.exe does
 * not support __attribute__, so we expand it to nothing under MSVC. Behavior is
 * unchanged; upb's own headers already select __declspec equivalents under
 * _MSC_VER, so only the single flatten hint is affected.
 */
#ifndef PROTOBUF_WIN_ARM64_MSVC_COMPAT_H_
#define PROTOBUF_WIN_ARM64_MSVC_COMPAT_H_

#if defined(_MSC_VER) && !defined(__clang__) && !defined(__GNUC__)
#define __attribute__(x)
#endif

#endif /* PROTOBUF_WIN_ARM64_MSVC_COMPAT_H_ */
