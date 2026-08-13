<!--
Survey stations: small hollow dark-grey circle, labelled with the station
name and its elevation in brackets, e.g. "MJ33 (197.5)".

Monochrome to match the rest of the plugin. The white halo keeps labels
readable where stations sit on top of floor strings.
-->
<qgis version="3.40.0" styleCategories="Symbology|Labeling">
  <renderer-v2 type="singleSymbol" forceraster="0" symbollevels="0" enableorderby="0">
    <symbols>
      <symbol type="marker" name="0" alpha="1" clip_to_extent="1" frame_rate="10" force_rhr="0" is_animated="0">
        <layer class="SimpleMarker" pass="0" enabled="1" locked="0">
          <Option type="Map">
            <Option type="QString" name="angle" value="0"/>
            <Option type="QString" name="cap_style" value="square"/>
            <Option type="QString" name="color" value="255,255,255,255"/>
            <Option type="QString" name="horizontal_anchor_point" value="1"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0"/>
            <Option type="QString" name="offset_unit" value="MM"/>
            <Option type="QString" name="outline_color" value="32,33,36,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="scale_method" value="diameter"/>
            <Option type="QString" name="size" value="2"/>
            <Option type="QString" name="size_map_unit_scale" value="3x:0,0,0,0,0,0"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="vertical_anchor_point" value="1"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fontFamily="Segoe UI" fontSize="8" fontSizeUnit="Point" fontWeight="50"
                  fontItalic="0" fontUnderline="0" fontStrikeout="0" textColor="32,33,36,255"
                  textOpacity="1" allowHtml="0" multilineHeight="1" capitalization="0"
                  fieldName="coalesce(&quot;PointId&quot;, '') || if(&quot;Elevation&quot; is null, '', ' (' || format_number(&quot;Elevation&quot;, 1) || ')')"
                  isExpression="1" namedStyle="Regular" blendMode="0" fontKerning="1"
                  fontLetterSpacing="0" fontWordSpacing="0" forcedBold="0" forcedItalic="0"
                  legendString="Aa" previewBkgrdColor="255,255,255,255" useSubstitutions="0">
        <text-buffer bufferDraw="1" bufferSize="1" bufferSizeUnits="MM" bufferColor="255,255,255,255"
                     bufferOpacity="1" bufferJoinStyle="128" bufferNoFill="1"
                     bufferSizeMapUnitScale="3x:0,0,0,0,0,0" bufferBlendMode="0"/>
        <text-mask maskEnabled="0" maskType="0" maskSize="0" maskSizeUnits="MM" maskOpacity="1"
                   maskJoinStyle="128" maskedSymbolLayers="" maskSizeMapUnitScale="3x:0,0,0,0,0,0"/>
        <background shapeDraw="0" shapeType="0" shapeSizeType="0" shapeSizeX="0" shapeSizeY="0"
                    shapeRotationType="0" shapeRotation="0" shapeOffsetX="0" shapeOffsetY="0"
                    shapeRadiiX="0" shapeRadiiY="0" shapeOpacity="1" shapeBlendMode="0"
                    shapeSizeUnit="Point" shapeOffsetUnit="Point" shapeRadiiUnit="Point"
                    shapeBorderWidth="0" shapeBorderWidthUnit="Point" shapeJoinStyle="64"
                    shapeFillColor="255,255,255,255" shapeBorderColor="128,128,128,255"/>
        <shadow shadowDraw="0" shadowUnder="0" shadowOffsetAngle="135" shadowOffsetDist="1"
                shadowOffsetUnit="MM" shadowOffsetGlobal="1" shadowRadius="1.5"
                shadowRadiusUnit="MM" shadowRadiusAlphaOnly="0" shadowOpacity="0.7"
                shadowScale="100" shadowColor="0,0,0,255" shadowBlendMode="6"/>
        <dd_properties>
          <Option type="Map">
            <Option type="QString" name="name" value=""/>
            <Option name="properties"/>
            <Option type="QString" name="type" value="collection"/>
          </Option>
        </dd_properties>
      </text-style>
      <text-format placeDirectionSymbol="0" decimals="3" plussign="0" addDirectionSymbol="0"
                   formatNumbers="0" wrapChar="" autoWrapLength="0" useMaxLineLengthForAutoWrap="1"
                   multilineAlign="3" leftDirectionSymbol="&lt;" rightDirectionSymbol=">"
                   reverseDirectionSymbol="0"/>
      <placement placement="1" placementFlags="0" dist="1.5" distUnits="MM" xOffset="0" yOffset="0"
                 offsetUnits="MM" quadOffset="4" rotationAngle="0" rotationUnit="0"
                 maxCurvedCharAngleIn="25" maxCurvedCharAngleOut="-25" priority="5"
                 overrunDistance="0" overrunDistanceUnit="MM" preserveRotation="1"
                 centroidWhole="0" centroidInside="0" fitInPolygonOnly="0" polygonPlacementFlags="2"
                 geometryGeneratorEnabled="0" geometryGeneratorType="PointGeometry"
                 layerType="PointGeometry" repeatDistance="0" repeatDistanceUnits="MM"
                 lineAnchorPercent="0.5" lineAnchorType="0" lineAnchorClipping="0"
                 lineAnchorTextPoint="FollowPlacement" overlapHandling="PreventOverlap"
                 allowDegraded="0" prioritization="PreferCloser"/>
      <rendering scaleVisibility="0" scaleMin="0" scaleMax="0" fontMinPixelSize="3"
                 fontMaxPixelSize="10000" fontLimitPixelSize="0" displayAll="0" upsidedownLabels="0"
                 labelPerPart="0" mergeLines="0" minFeatureSize="0" obstacle="1" obstacleFactor="1"
                 obstacleType="1" zIndex="0" limitNumLabels="0" maxNumLabels="2000"
                 unplacedVisibility="0" drawLabels="1"/>
      <dd_properties>
        <Option type="Map">
          <Option type="QString" name="name" value=""/>
          <Option name="properties"/>
          <Option type="QString" name="type" value="collection"/>
        </Option>
      </dd_properties>
      <callout type="simple">
        <Option type="Map">
          <Option type="QString" name="anchorPoint" value="pole_of_inaccessibility"/>
          <Option type="int" name="blendMode" value="0"/>
          <Option type="QString" name="drawToAllParts" value="false"/>
          <Option type="QString" name="enabled" value="0"/>
          <Option type="QString" name="labelAnchorPoint" value="point_on_exterior"/>
          <Option type="QString" name="minLength" value="0"/>
          <Option type="QString" name="minLengthUnit" value="MM"/>
          <Option type="QString" name="offsetFromAnchor" value="0"/>
          <Option type="QString" name="offsetFromAnchorUnit" value="MM"/>
          <Option type="QString" name="offsetFromLabel" value="0"/>
          <Option type="QString" name="offsetFromLabelUnit" value="MM"/>
        </Option>
      </callout>
    </settings>
  </labeling>
  <layerGeometryType>0</layerGeometryType>
</qgis>
