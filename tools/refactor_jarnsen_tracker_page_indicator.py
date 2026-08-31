#!/usr/bin/env python3
"""Add compact x/5 page numbering to the Tracker Unified-Core pages.

The tracker display implementation is still being migrated into the shared
renderer. Keep this transformation deterministic and fail loudly if the
expected source seams move, just like the existing ServiceWeb/boot-splash
migration transforms.
"""

from pathlib import Path

PATH = Path("src/vehicle/TrackerStatusModule.cpp")

source = PATH.read_text(encoding="utf-8")

helper = r'''void drawPagePosition(OLEDDisplay *display, int16_t x, int16_t y, jarnsen::DisplayPage page)
{
    if (!display)
        return;
    char text[8] = {};
    std::snprintf(text, sizeof(text), "%u/%u", (unsigned)jarnsen::displayPageNumber(page),
                  (unsigned)jarnsen::displayPageCount());
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    display->drawString(x + 2, y + 1, text);
}

'''

if "void drawPagePosition(" not in source:
    anchor = "void drawHeader(OLEDDisplay *display, int16_t x, int16_t y, const char *title)\n"
    if anchor not in source:
        raise SystemExit("TrackerStatusModule drawHeader seam not found")
    source = source.replace(anchor, helper + anchor, 1)

# RADIO used the far-left header position for EU868. Leave room for the page
# counter while retaining the region/profile/battery information.
old_radio = '    display->drawString(x + 2, y + 1, regionText());\n'
new_radio = '    display->drawString(x + 28, y + 1, regionText());\n'
if old_radio in source:
    source = source.replace(old_radio, new_radio, 1)
elif new_radio not in source:
    raise SystemExit("TrackerStatusModule RADIO header seam not found")

old_tail = '''        default:
            drawMgrsPage(display, x, y);
            break;
        }
    }
};
'''
new_tail = '''        default:
            drawMgrsPage(display, x, y);
            break;
        }

        // Keep the page counter independent of each page's content so all five
        // Unified-Core pages consistently show 1/5 ... 5/5. Menus and node
        // navigation return before this point and therefore stay uncluttered.
        drawPagePosition(display, x, y, currentPage);
    }
};
'''
if old_tail in source:
    source = source.replace(old_tail, new_tail, 1)
elif "drawPagePosition(display, x, y, currentPage);" not in source:
    raise SystemExit("TrackerStatusModule drawFrame tail seam not found")

PATH.write_text(source, encoding="utf-8")
print("Tracker page indicator routed: 1/5 ... 5/5")
